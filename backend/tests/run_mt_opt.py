"""Run the MetaTrader all-pairs optimizer for one user from the command line (same code as POST /api/bot/mt-optimize)."""
import asyncio
import sys
import time
import uuid

sys.path.insert(0, "/app/backend")
import server  # noqa: E402


async def main(uid: str):
    job = {"job_id": uuid.uuid4().hex[:12], "user_id": uid, "status": "running", "started": time.time(),
           "current": "A ler os símbolos da corretora", "step": 0, "total": 0, "found": {"setups": 0, "c12": 0, "c20": 0}}
    await server._save_mt_job(job)
    await server._mt_optimize(job)
    print(job["status"], job.get("error"), job.get("found"))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
