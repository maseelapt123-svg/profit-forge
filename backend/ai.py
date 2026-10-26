"""LLM helpers: trade-entry filter for the bots and loss-review prompt building."""
import asyncio
import json
import logging
import os
import re
import uuid

from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage

logger = logging.getLogger("ai")

FILTER_SYSTEM = (
    "És um gestor de risco de trading quantitativo. Recebes um sinal de entrada gerado por um robô e o contexto de "
    "mercado. Decide se o robô deve entrar. Rejeita entradas contra a tendência dominante, em exaustão (RSI extremo "
    "no sentido da entrada), com volatilidade anormal ou quando a estatística da estratégia é fraca. "
    "Responde APENAS com JSON numa linha: {\"approve\": true|false, \"confidence\": 0-100, \"reason\": \"máx 12 palavras em português\"}"
)


async def ai_filter(context: str, timeout: float = 15) -> dict:
    """Returns {approve, confidence, reason}. Fails closed (no entry) when the AI is unavailable."""
    chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"filter_{uuid.uuid4().hex}",
                   system_message=FILTER_SYSTEM).with_model("openai", "gpt-5.4-mini")
    async def collect() -> str:
        out = []
        async for ev in chat.stream_message(UserMessage(text=context)):
            if isinstance(ev, TextDelta):
                out.append(ev.content)
            elif isinstance(ev, StreamDone):
                break
        return "".join(out)

    try:
        txt = await asyncio.wait_for(collect(), timeout)
        m = re.search(r"\{.*\}", txt, re.S)
        d = json.loads(m.group(0)) if m else {}
        return {"approve": bool(d.get("approve")), "confidence": int(d.get("confidence", 0)),
                "reason": str(d.get("reason", ""))[:120] or "sem justificação"}
    except Exception as e:  # external boundary
        logger.warning("ai filter failed: %s", e)
        return {"approve": False, "confidence": 0, "reason": "IA indisponível — entrada cancelada por segurança"}


REVIEW_SYSTEM = (
    "És um coach de trading profissional. Analisas o histórico de perdas de um robô de trading em conta simulada e "
    "explicas, em português de Portugal, PORQUÊ está a perder e O QUE mudar. Sê concreto e usa os números fornecidos. "
    "Estrutura em markdown simples com as secções: **Resumo**, **Porque está a perder**, **Correções recomendadas** "
    "(lista numerada, cada uma com o ajuste exato: parâmetro, valor, filtro, horário, par), **O que está a funcionar**, "
    "**Próximo passo**. Máximo ~250 palavras. Valores monetários em dólares ($). Não uses nomes técnicos de chaves nem "
    "backticks; descreve as definições pelo nome em português (ex.: «Só a favor da tendência», «Acerto mínimo»). "
    "Nunca prometas lucro; termina com uma linha a lembrar que não é aconselhamento financeiro."
)

LABELS = {
    "source": "Fonte", "pairs": "Pares", "expiry": "Expiração (min)", "amount": "Valor por entrada ($)",
    "min_winrate": "Acerto mínimo (%)", "strategy": "Estratégia", "min_votes": "Votos de confluência",
    "max_per_hour": "Máx. entradas/hora", "auto_fix": "Correção automática", "ai_filter": "Filtro IA",
    "symbols": "Ativos", "tf": "Timeframe", "risk_pct": "Risco por operação (%)", "sl_atr": "Stop (x ATR)",
    "rr": "Rácio R:R", "max_positions": "Máx. posições", "trend_filter": "Filtro de tendência EMA200",
    "mtf": "Confirmação TF superior", "setups": "Setups otimizados", "hours": "Horas bloqueadas (UTC)",
    "pair_rules": "Par/estratégia em quarentena", "trend_align": "Só a favor da tendência",
    "skip_low_vol": "Ignorar volatilidade baixa", "skip_high_vol": "Ignorar volatilidade extrema",
    "paused": "Setups em quarentena", "force_mtf": "Confirmação TF superior obrigatória", "widen_stop": "Stop 0,5x ATR mais largo",
    "conf_votes": "Confluência: mín. plugins", "conf_score": "Confluência: pontuação mín. (%)",
    "remove_pairs": "Remover pares", "remove_symbols": "Remover ativos", "plugin_on": "Ativar plugin", "plugin_off": "Desativar plugin",
    "plugins_ativos": "Plugins ativos",
}


def labeled(d: dict) -> str:
    def v(x):
        return "sim" if x is True else "não" if x is False else x
    return "; ".join(f"{LABELS.get(k, k)}: {v(x)}" for k, x in d.items()) or "nenhuma"


def review_prompt(scope: str, an: dict, fixes: dict, config: dict) -> str:
    probs = "\n".join(f"- {p['text']} ({p['n']} ops, {p['winrate']:.0f}% acerto)" for p in an["problems"]) or "nenhum detetado"
    losses = "\n".join(f"- {json.dumps(x, ensure_ascii=False, default=str)}" for x in an.get("recent_losses", [])[:12]) or "nenhuma"
    head = "Robô HFX (opções binárias 1/3 min, payout fixo)" if scope == "hfx" else "Robô principal (posições com SL/TP)"
    extra = f"Ponto de equilíbrio do acerto: {an['breakeven']:.1f}%\n" if "breakeven" in an else f"Resultado: {an.get('pnl', 0):+.2f} $\n"
    return (f"{head}\nOperações analisadas: {an['trades']} · Perdas: {an['losses']} · Acerto: {an['winrate']:.1f}%\n{extra}"
            f"Configuração atual: {labeled(config)}\n"
            f"Correções automáticas já ativas: {labeled(fixes)}\n"
            f"Padrões de perda detetados pelo motor estatístico:\n{probs}\n"
            f"Últimas perdas (contexto de entrada):\n{losses}")


DAILY_SYSTEM = (
    "És um gestor de trading que escreve o relatório diário dos robôs de uma conta simulada, em português de Portugal. "
    "Usa os números fornecidos e valores em dólares ($). Estrutura em markdown simples: **Resultado do dia** (1-2 frases), "
    "**Robô HFX** e **Robô principal** (o que correu bem/mal, melhores e piores pares/estratégias — omite a secção se o robô "
    "não operou), **Ajustes para amanhã** (lista numerada de 3 a 5 ajustes concretos: definição, valor exato, par/horário a "
    "evitar ou priorizar), **Nota de risco** (1 frase). Não uses nomes técnicos de chaves nem backticks. Máximo ~280 palavras. "
    "Nunca prometas lucro."
)


def daily_prompt(date: str, stats: dict) -> str:
    def block(name: str, s: dict) -> str:
        if not s["trades"]:
            return f"{name}: não operou neste dia.\n"
        groups = "\n".join(f"  - {g['label']}: {g['trades']} ops, {g['winrate']:.0f}% acerto, {g['pnl']:+.2f} $" for g in s["groups"])
        return (f"{name}: {s['trades']} operações, {s['wins']} ganhos, acerto {s['winrate']:.1f}%, resultado {s['pnl']:+.2f} $, "
                f"entradas rejeitadas pela IA: {s['ai_rejected']}, ignoradas pela correção automática: {s['fix_skipped']}.\n"
                f"  Por par/estratégia:\n{groups}\n  Horas com perdas (UTC): {s['bad_hours'] or 'nenhuma'}\n"
                f"  Configuração: {labeled(s['config'])}\n  Correções ativas: {labeled(s['fixes'])}\n")
    extra = f"Ponto de equilíbrio do acerto HFX: {stats['hfx']['breakeven']:.1f}%\n"
    return f"Relatório do dia {date} (UTC).\n{extra}{block('Robô HFX', stats['hfx'])}{block('Robô principal', stats['bot'])}"


ADJ_SYSTEM = (
    "Converte o relatório diário de trading em ajustes concretos de configuração. Responde APENAS com um array JSON "
    "(sem texto à volta) de 0 a 6 objetos {\"scope\": \"hfx\"|\"bot\", \"field\": <campo>, \"value\": <valor>, "
    "\"reason\": \"máx 12 palavras em português\"}. Usa só os campos permitidos e valores dentro dos limites. "
    "Só sugere ajustes para robôs que operaram e só quando os dados os justificam."
)


async def ai_adjustments(report: str, allowed: str, timeout: float = 45) -> list:
    chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"adj_{uuid.uuid4().hex}",
                   system_message=ADJ_SYSTEM).with_model("openai", "gpt-5.4")

    async def collect() -> str:
        out = []
        async for ev in chat.stream_message(UserMessage(text=f"{allowed}\n\nRelatório:\n{report}")):
            if isinstance(ev, TextDelta):
                out.append(ev.content)
            elif isinstance(ev, StreamDone):
                break
        return "".join(out)
    try:
        txt = await asyncio.wait_for(collect(), timeout)
        m = re.search(r"\[.*\]", txt, re.S)
        data = json.loads(m.group(0)) if m else []
        return [d for d in data if isinstance(d, dict)][:6]
    except Exception as e:  # external boundary
        logger.warning("ai adjustments failed: %s", e)
        return []


def daily_chat() -> LlmChat:
    return LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"daily_{uuid.uuid4().hex}",
                   system_message=DAILY_SYSTEM).with_model("openai", "gpt-5.4")


def review_chat() -> LlmChat:
    return LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"review_{uuid.uuid4().hex}",
                   system_message=REVIEW_SYSTEM).with_model("openai", "gpt-5.4")
