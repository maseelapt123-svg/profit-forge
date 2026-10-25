import React, { useState } from "react";
import { View } from "react-native";
import Svg, { Line, Polyline, Rect, Text as SvgText, Defs, LinearGradient, Stop, Polygon } from "react-native-svg";

import { fonts, useTheme } from "@/src/theme";

export type Candle = { t: number; o: number; h: number; l: number; c: number };
export type Zone = { dir: "bull" | "bear"; top: number; bottom: number; idx: number };
export type Struct = { type: string; dir: "bull" | "bear"; price: number; idx: number; break_idx: number };

const AXIS = 58;

export type Series = { data: (number | null)[]; color: string };
export type HLine = { price: number; color: string; label?: string };

export function CandleChart({ candles, obs = [], fvgs = [], structure = [], height = 320, decimals = 2, show, lines = [], hlines = [] }: {
  candles: Candle[]; obs?: Zone[]; fvgs?: Zone[]; structure?: Struct[]; height?: number; decimals?: number;
  show: { ob: boolean; fvg: boolean; bos: boolean }; lines?: Series[]; hlines?: HLine[];
}) {
  const { colors } = useTheme();
  const [w, setW] = useState(0);
  const n = candles.length;
  let hi = -Infinity;
  let lo = Infinity;
  candles.forEach((k) => {
    hi = Math.max(hi, k.h);
    lo = Math.min(lo, k.l);
  });
  const pad = (hi - lo) * 0.06 || 1;
  hi += pad;
  lo -= pad;
  const plotW = Math.max(0, w - AXIS);
  const cw = n ? plotW / n : 0;
  const y = (p: number) => ((hi - p) / (hi - lo)) * height;
  const x = (i: number) => Math.max(0, i) * cw + cw / 2;
  const last = candles[n - 1];
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => hi - (hi - lo) * f);
  const clampZone = (z: Zone) => ({ ...z, top: Math.min(z.top, hi), bottom: Math.max(z.bottom, lo) });

  return (
    <View onLayout={(e) => setW(e.nativeEvent.layout.width)} style={{ height }} testID="candle-chart">
      {w > 0 && n > 0 && (
        <Svg width={w} height={height}>
          {ticks.map((p, i) => (
            <React.Fragment key={i}>
              <Line x1={0} x2={plotW} y1={y(p)} y2={y(p)} stroke={colors.divider} strokeWidth={0.5} />
              <SvgText x={plotW + 6} y={Math.min(height - 3, Math.max(10, y(p) + 4))} fill={colors.muted} fontSize={10} fontFamily={fonts.text}>
                {p.toFixed(decimals)}
              </SvgText>
            </React.Fragment>
          ))}
          {show.fvg &&
            fvgs.map((z, i) => {
              const c = clampZone(z);
              if (c.top <= c.bottom) return null;
              return (
                <Rect key={`f${i}`} x={x(z.idx) - cw / 2} y={y(c.top)} width={plotW - (x(z.idx) - cw / 2)} height={y(c.bottom) - y(c.top)}
                  fill={z.dir === "bull" ? colors.success : colors.error} opacity={0.1} />
              );
            })}
          {show.ob &&
            obs.map((z, i) => {
              const c = clampZone(z);
              if (c.top <= c.bottom) return null;
              const x0 = x(z.idx) - cw / 2;
              return (
                <React.Fragment key={`o${i}`}>
                  <Rect x={x0} y={y(c.top)} width={plotW - x0} height={Math.max(2, y(c.bottom) - y(c.top))}
                    fill={z.dir === "bull" ? colors.success : colors.error} opacity={0.22}
                    stroke={z.dir === "bull" ? colors.success : colors.error} strokeWidth={0.5} />
                  <SvgText x={x0 + 4} y={y(c.top) + 11} fill={z.dir === "bull" ? colors.success : colors.error} fontSize={9} fontFamily={fonts.display}>
                    OB
                  </SvgText>
                </React.Fragment>
              );
            })}
          {candles.map((k, i) => {
            const up = k.c >= k.o;
            const col = up ? colors.success : colors.error;
            const bt = y(Math.max(k.o, k.c));
            const bh = Math.max(1, Math.abs(y(k.o) - y(k.c)));
            return (
              <React.Fragment key={k.t}>
                <Line x1={x(i)} x2={x(i)} y1={y(k.h)} y2={y(k.l)} stroke={col} strokeWidth={1} />
                <Rect x={x(i) - cw * 0.35} y={bt} width={Math.max(1, cw * 0.7)} height={bh} fill={col} />
              </React.Fragment>
            );
          })}
          {hlines
            .filter((hl) => hl.price < hi && hl.price > lo)
            .map((hl, i) => (
              <React.Fragment key={`h${i}`}>
                <Line x1={0} x2={plotW} y1={y(hl.price)} y2={y(hl.price)} stroke={hl.color} strokeWidth={0.8} strokeDasharray="6,4" opacity={0.8} />
                {hl.label ? (
                  <SvgText x={4} y={y(hl.price) - 3} fill={hl.color} fontSize={9} fontFamily={fonts.display}>
                    {hl.label}
                  </SvgText>
                ) : null}
              </React.Fragment>
            ))}
          {lines.map((ln, li) => {
            const pts = ln.data
              .map((v, i) => (v === null || v > hi || v < lo ? null : `${x(i)},${y(v)}`))
              .filter(Boolean)
              .join(" ");
            return pts ? <Polyline key={`l${li}`} points={pts} fill="none" stroke={ln.color} strokeWidth={1.4} /> : null;
          })}
          {show.bos &&
            structure.map((s, i) => {
              const col = s.dir === "bull" ? colors.success : colors.error;
              const x1 = x(s.idx);
              const x2 = x(s.break_idx);
              return (
                <React.Fragment key={`s${i}`}>
                  <Line x1={x1} x2={x2} y1={y(s.price)} y2={y(s.price)} stroke={col} strokeWidth={1} strokeDasharray="4,3" />
                  <SvgText x={(x1 + x2) / 2 - 12} y={y(s.price) + (s.dir === "bull" ? -4 : 12)} fill={col} fontSize={9} fontFamily={fonts.display}>
                    {s.type}
                  </SvgText>
                </React.Fragment>
              );
            })}
          {last && (
            <>
              <Line x1={0} x2={plotW} y1={y(last.c)} y2={y(last.c)} stroke={colors.brandPrimary} strokeWidth={0.8} strokeDasharray="2,2" />
              <Rect x={plotW + 2} y={y(last.c) - 9} width={AXIS - 2} height={18} rx={3} fill={colors.brandPrimary} />
              <SvgText x={plotW + 6} y={y(last.c) + 4} fill={colors.onBrandPrimary} fontSize={10} fontFamily={fonts.display}>
                {last.c.toFixed(decimals)}
              </SvgText>
            </>
          )}
        </Svg>
      )}
    </View>
  );
}

export function LineChart({ data, height = 180, testID, baseline }: { data: number[]; height?: number; testID?: string; baseline?: number }) {
  const { colors } = useTheme();
  const [w, setW] = useState(0);
  const max = Math.max(...data, baseline ?? -Infinity);
  const min = Math.min(...data, baseline ?? Infinity);
  const range = max - min || 1;
  const up = data[data.length - 1] >= (baseline ?? data[0]);
  const col = up ? colors.success : colors.error;
  const pts = data.map((v, i) => `${(i / Math.max(1, data.length - 1)) * w},${height - 8 - ((v - min) / range) * (height - 16)}`);
  return (
    <View onLayout={(e) => setW(e.nativeEvent.layout.width)} style={{ height }} testID={testID}>
      {w > 0 && data.length > 1 && (
        <Svg width={w} height={height}>
          <Defs>
            <LinearGradient id="g" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={col} stopOpacity={0.25} />
              <Stop offset="1" stopColor={col} stopOpacity={0} />
            </LinearGradient>
          </Defs>
          {baseline !== undefined && (
            <Line x1={0} x2={w} y1={height - 8 - ((baseline - min) / range) * (height - 16)} y2={height - 8 - ((baseline - min) / range) * (height - 16)}
              stroke={colors.borderStrong} strokeDasharray="4,4" strokeWidth={1} />
          )}
          <Polygon points={`0,${height} ${pts.join(" ")} ${w},${height}`} fill="url(#g)" />
          <Polyline points={pts.join(" ")} fill="none" stroke={col} strokeWidth={2} />
        </Svg>
      )}
    </View>
  );
}

export function Sparkline({ data, width = 64, height = 28 }: { data: number[]; width?: number; height?: number }) {
  const { colors } = useTheme();
  if (data.length < 2) return <View style={{ width, height }} />;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const r = max - min || 1;
  const col = data[data.length - 1] >= data[0] ? colors.success : colors.error;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * width},${height - 2 - ((v - min) / r) * (height - 4)}`).join(" ");
  return (
    <Svg width={width} height={height}>
      <Polyline points={pts} fill="none" stroke={col} strokeWidth={1.5} />
    </Svg>
  );
}

export function RsiPanel({ data, height = 90 }: { data: (number | null)[]; height?: number }) {
  const { colors } = useTheme();
  const [w, setW] = useState(0);
  const plotW = Math.max(0, w - AXIS);
  const y = (v: number) => height - (v / 100) * height;
  const n = data.length || 1;
  const pts = data.map((v, i) => (v === null ? null : `${(i + 0.5) * (plotW / n)},${y(v)}`)).filter(Boolean).join(" ");
  const last = [...data].reverse().find((v) => v !== null) ?? 50;
  return (
    <View onLayout={(e) => setW(e.nativeEvent.layout.width)} style={{ height }} testID="rsi-panel">
      {w > 0 && (
        <Svg width={w} height={height}>
          <Rect x={0} y={y(70)} width={plotW} height={y(30) - y(70)} fill={colors.brandPrimary} opacity={0.06} />
          {[30, 50, 70].map((v) => (
            <React.Fragment key={v}>
              <Line x1={0} x2={plotW} y1={y(v)} y2={y(v)} stroke={colors.divider} strokeWidth={0.6} strokeDasharray={v === 50 ? "2,3" : undefined} />
              <SvgText x={plotW + 6} y={y(v) + 4} fill={colors.muted} fontSize={10} fontFamily={fonts.text}>
                {v}
              </SvgText>
            </React.Fragment>
          ))}
          <Polyline points={pts} fill="none" stroke={colors.info} strokeWidth={1.4} />
          <SvgText x={4} y={12} fill={colors.info} fontSize={10} fontFamily={fonts.display}>
            {`RSI 14 · ${(last as number).toFixed(1)}`}
          </SvgText>
        </Svg>
      )}
    </View>
  );
}
