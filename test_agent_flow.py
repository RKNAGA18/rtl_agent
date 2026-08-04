import asyncio
from agent import run_agent

async def main():
    events = []
    async for ev in run_agent("Design an 8-bit synchronous up-counter with active-high synchronous reset and enable"):
        events.append(ev)
    print(f"Total events emitted: {len(events)}")
    print(f"Last event type: {events[-1]['type']}")
    print(f"Final result: {events[-1]['data']}")

if __name__ == "__main__":
    asyncio.run(main())
