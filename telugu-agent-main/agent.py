import logging
import asyncio
import re
import os
from dotenv import load_dotenv

from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google, sarvam

# Load env
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-agent")


class VoiceAgent(Agent):
    def __init__(self, room) -> None:
        self.step = 0
        self.room = room

        super().__init__(
            instructions="""
You are Telugu Bhavik, a Telugu voice assistant for Vridhi housing loans.

Rules:
- Speak natural Telugu
- Be friendly
- Ask one question at a time
- Keep responses short
""",

            # 🎤 STT
            stt=sarvam.STT(
                language="te-IN",
                model="saaras:v3",
                mode="transcribe"
            ),

            # 🧠 LLM
            llm=google.LLM(
                model="gemini-1.5-flash"
            ),

            # 🔊 TTS (TELUGU FIX)
            tts=sarvam.TTS(
                target_language_code="te-IN",
                model="bulbul:v3",
                speaker="shubh"
            ),
        )

    async def on_user_message(self, message: str):
        logger.info(f"👤 User: {message}")

        text = message.lower()

        # STEP 1
        if self.step == 0:
            self.step = 1

            await self.session.generate_reply(
                instructions="మీ పేరు చెప్పగలరా?"
            )
            return

        # STEP 2
        elif self.step == 1:
            self.step = 2

            await self.session.generate_reply(
                instructions="మీ నెలవారీ ఆదాయం ఎంత?"
            )
            return

        # STEP 3
        elif self.step == 2:
            self.step = 3

            await self.session.generate_reply(
                instructions="మీరు ఉద్యోగం చేస్తున్నారా లేక బిజినెస్ చేస్తున్నారా?"
            )
            return

        # STEP 4
        elif self.step == 3:
            self.step = 4

            await self.session.generate_reply(
                instructions="మీకు ఎంత లోన్ కావాలి?"
            )
            return

        # FINAL STEP
        elif self.step == 4:

            if "no" in text or "అవసరం లేదు" in text:
                await self.session.generate_reply(
                    instructions="సరే, ధన్యవాదాలు!"
                )

                await asyncio.sleep(2)
                await self.session.aclose()
                await self.room.disconnect()
                return

            await self.session.generate_reply(
                instructions="""
ధన్యవాదాలు!

మా టీమ్ త్వరలో మీతో సంప్రదిస్తుంది.
"""
            )

            await asyncio.sleep(2)
            await self.session.aclose()
            await self.room.disconnect()


# 🚀 FIXED ENTRYPOINT (IMPORTANT PART)
async def entrypoint(ctx: JobContext):
    logger.info("🚀 Connecting to LiveKit...")

    await ctx.connect()
    participant = await ctx.wait_for_participant()

    logger.info("✅ Participant joined")

    agent = VoiceAgent(room=ctx.room)
    session = AgentSession()

    await session.start(
        agent=agent,
        room=ctx.room,
    )

    logger.info("🎤 Agent started")

    # 🔥 CRITICAL FIX → delay before speaking
    await asyncio.sleep(2)

    # 🔥 FORCE INTRO (this was missing before)
    await agent.session.generate_reply(
        instructions="""
నమస్తే!

నేను వృద్ధి నుండి మాట్లాడుతున్నాను.
మేము 14–15% వడ్డీతో హౌస్ లోన్స్ అందిస్తున్నాము.

మీకు హౌస్ లోన్ అవసరమా?
"""
    )


# ▶️ Run
if __name__ == "__main__":
    print("🚀 Starting Telugu Bhavik...")
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="telugu-bhavik"
        )
    )