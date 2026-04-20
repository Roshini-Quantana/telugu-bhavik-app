import logging
from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google, sarvam

# Load env
load_dotenv()

# Logging
logger = logging.getLogger("voice-agent")
logger.setLevel(logging.INFO)


class VoiceAgent(Agent):
    def __init__(self) -> None:
        self.mode = "SALES"  # SALES → PD

        super().__init__(

            # 🧠 MASTER INSTRUCTIONS (Sales + PD)
            instructions="""
You are Telugu Bhavik, an AI voice agent for Vridhi housing loans.

You operate in TWO MODES:

=====================
MODE 1: SALES AGENT
=====================
Goal:
- Introduce housing loans (14–15%)
- Ask questions step-by-step:
  - Monthly income
  - Job type
  - Location
  - Property stage
  - Loan amount

Rules:
- Speak Telugu naturally (mix English if needed)
- Be friendly and conversational
- Ask ONE question at a time
- Keep answers short

Lead Types:
- HOT → ready now
- WARM → interested later
- COLD → not interested

If HOT:
Say:
"మా సీనియర్ టీమ్ మీతో త్వరలో సంప్రదిస్తుంది"

Then MOVE to PD mode.

If COLD:
Politely end conversation.

=====================
MODE 2: PD AGENT
=====================
Goal:
Collect verification details.

Ask:
- Employment details
- Income stability
- Existing loans
- Family details
- Property details

Rules:
- Be formal
- Ask ONE question at a time
- Do not skip

At end:
Summarize clearly.

=====================
IMPORTANT:
- Start in SALES mode
- If user shows strong intent → switch to PD
- Keep conversation natural
""",

            # 🎤 Speech to Text
            stt=sarvam.STT(
                language="en-IN",
                model="saaras:v3",
                mode="transcribe"
            ),

            # 🧠 Gemini LLM
            llm=google.LLM(model="gemini-2.5-flash"),

            # 🔊 Text to Speech
            tts=sarvam.TTS(
                target_language_code="en-IN",
                model="bulbul:v3",
                speaker="shubh"
            ),
        )

        logger.info("VoiceAgent initialized")

    # 👋 When user joins
    async def on_enter(self):
        logger.info("User joined → starting SALES flow")

        await self.session.generate_reply(
            instructions="""
You are in SALES mode.

Greet the user warmly in Telugu.

Introduce Vridhi housing loans briefly (14–15%).

Then ask first question:
"What is your monthly income?"
"""
        )

    # 🔥 Detect user input and switch mode
    async def on_user_message(self, message: str):
        text = message.lower()

        # Detect HOT lead
        if self.mode == "SALES" and (
            "ఇప్పుడే" in text or
            "immediate" in text or
            "now" in text
        ):
            logger.info("HOT lead detected → switching to PD")

            self.mode = "PD"

            await self.session.generate_reply(
                instructions="""
User is a HOT lead.

Say:
"మా సీనియర్ టీమ్ మీతో త్వరలో సంప్రదిస్తుంది"

Now switch to PD mode.

Ask first PD question:
"What is your employment type?"
"""
            )


# 🚀 Entry point (LiveKit)
async def entrypoint(ctx: JobContext):
    logger.info(f"Connected to room: {ctx.room.name}")

    await ctx.connect()
    await ctx.wait_for_participant()

    logger.info("Participant joined → starting session")

    session = AgentSession()

    await session.start(
        agent=VoiceAgent(),
        room=ctx.room,
    )

    logger.info("Agent is live")


# ▶️ Run app
if __name__ == "__main__":
    print("🚀 Starting Telugu Bhavik agent...")
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="telugu-bhavik"
        )
    )