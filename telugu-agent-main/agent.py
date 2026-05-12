import logging
import asyncio
import os
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from livekit.agents import JobContext, WorkerOptions, cli, AutoSubscribe
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.llm import ChatContext
from livekit.plugins import google, sarvam, silero, openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

# --- Environment Validation ---
REQUIRED_ENV_VARS = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "SARVAM_API_KEY", "GOOGLE_API_KEY"]
missing_vars = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if missing_vars:
    print(f"CRITICAL: Missing environment variables: {', '.join(missing_vars)}")
    # We don't exit here to allow local debugging, but it will likely fail later.

# ----------------------------------------------------------
# --- Monkeypatch for Sarvam STT language_code null bug ---
import livekit.plugins.sarvam.stt as sarvam_stt
_orig_handle_transcript_data = sarvam_stt.SpeechStream._handle_transcript_data

async def _patched_handle_transcript_data(self, data):
    if "data" in data and isinstance(data["data"], dict):
        # If Sarvam returns null for language_code, default to te-IN
        if data["data"].get("language_code") is None:
            data["data"]["language_code"] = "te-IN"
    return await _orig_handle_transcript_data(self, data)

sarvam_stt.SpeechStream._handle_transcript_data = _patched_handle_transcript_data
# ----------------------------------------------------------

BASE_DIR = Path(__file__).parent
CREDS_PATH = str(BASE_DIR / "creds.json")

# Set GOOGLE_APPLICATION_CREDENTIALS if file exists
if os.path.exists(CREDS_PATH):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDS_PATH

# Use gemini-flash-latest as gemini-1.5-flash was reporting 404 in this environment
GEMINI_MODEL = "gemini-flash-latest"

SPREADSHEET_NAME = os.environ.get("SHEET_NAME", "Vridhi_leads_crm")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("voice-agent")
logger.setLevel(logging.INFO)

# ----------------------------------------------------------------------
# Sheet schemas
# ----------------------------------------------------------------------
LEAD_HEADERS = ["call_id", "name", "company_name", "job_type", "income",
                "current_location", "property_location", "loan_amount", "property_stage", 
                "lead_type", "interest_level"]
PD_HEADERS = ["call_id", "employment_type", "job_duration", "salary_type",
              "existing_loans", "family_details", "property_details", "pd_summary"]
TRANSCRIPT_HEADERS = ["call_id", "timestamp", "role", "text"]
CALL_LOG_HEADERS = ["call_id", "started_at", "mode", "lead_type", "status"]



# ----------------------------------------------------------------------
# Google Sheets
# ----------------------------------------------------------------------
def init_google_sheets():
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        
        # Check environment variable first (for production)
        json_creds = os.environ.get("GOOGLE_SHEETS_JSON")
        if json_creds:
            try:
                creds_dict = json.loads(json_creds)
                creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
                logger.info("Initialized Google Sheets using GOOGLE_SHEETS_JSON environment variable")
            except Exception as json_err:
                logger.error(f"Failed to parse GOOGLE_SHEETS_JSON: {json_err}")
                return None
        elif os.path.exists(CREDS_PATH):
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
            logger.info(f"Initialized Google Sheets using {CREDS_PATH}")
        else:
            logger.error("No Google Sheets credentials found (creds.json or GOOGLE_SHEETS_JSON)")
            return None

        client = gspread.authorize(creds)
        sh = client.open(SPREADSHEET_NAME)
        sheets = {
            "call_logs": sh.worksheet("call_logs"),
            "lead_details": sh.worksheet("lead_details"),
            "pd_verification": sh.worksheet("pd_verification"),
            "transcripts": sh.worksheet("transcripts"),
        }
        return sheets
    except Exception as e:
        logger.exception(f"Sheets init failed: {e}")
        return None


def sync_headers(state):
    """Automatically updates Row 1 of all sheets to match the code's headers."""
    sheets = state.get("sheets")
    if not sheets:
        return
    try:
        # Sync headers for all main tables
        async def _sync():
            await asyncio.to_thread(sheets["lead_details"].update, values=[LEAD_HEADERS], range_name="A1")
            await asyncio.to_thread(sheets["pd_verification"].update, values=[PD_HEADERS], range_name="A1")
            await asyncio.to_thread(sheets["transcripts"].update, values=[TRANSCRIPT_HEADERS], range_name="A1")
            await asyncio.to_thread(sheets["call_logs"].update, values=[CALL_LOG_HEADERS], range_name="A1")
            logger.info("Google Sheet headers synchronized successfully")
        
        asyncio.create_task(_sync())
    except Exception as e:
        logger.warning(f"Header sync failed: {e}")


def build_row(data, headers):
    return [str(data.get(h, "") or "") for h in headers]


def parse_extraction(text):
    if not text:
        return None
    try:
        raw = text.replace("```json", "").replace("```", "").strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        logger.warning(f"parse_extraction failed: {e}")
    return None


async def upsert_row(state, table, data, headers):
    sheets = state.get("sheets")
    lock = state["lock"]
    call_id = state.get("call_id")

    if not sheets or table not in sheets:
        logger.warning(f"upsert_row skipped: sheets not ready (table={table})")
        return

    def _do():
        ws = sheets[table]
        row = build_row(data, headers)
        
        # Always search the sheet for the call_id to ensure no duplicates
        ids = ws.col_values(1)
        try:
            row_idx = ids.index(call_id) + 1
            ws.update(values=[row], range_name=f"A{row_idx}")
            logger.info(f"Updated {table} row {row_idx} for {call_id}")
        except ValueError:
            ws.append_row(row)
            logger.info(f"Appended new {table} row for {call_id}")

    async with lock:
        try:
            await asyncio.to_thread(_do)
        except Exception as e:
            logger.exception(f"Sync {table} failed: {e}")


async def append_transcript(state, role, text):
    sheets = state.get("sheets")
    if not sheets or "transcripts" not in sheets:
        return
    row = [state["call_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), role, text]
    async with state["lock"]:
        try:
            await asyncio.to_thread(sheets["transcripts"].append_row, row)
        except Exception as e:
            logger.exception(f"transcript append failed: {e}")


async def append_call_log(state, mode, lead_type, status):
    sheets = state.get("sheets")
    if not sheets or "call_logs" not in sheets:
        return
    row = [state["call_id"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mode, lead_type, status]
    async with state["lock"]:
        try:
            await asyncio.to_thread(sheets["call_logs"].append_row, row)
            logger.info("call_logs initial row written")
        except Exception as e:
            logger.exception(f"call_logs append failed: {e}")


# ----------------------------------------------------------------------
# Background extraction (LLM -> JSON -> Sheets)
# ----------------------------------------------------------------------
async def extract_and_sync(state, text):
    try:
        # Wait for sheets to be ready, but don't loop forever if it failed
        while state.get("sheets") is None:
            if state.get("sheets_failed"):
                logger.warning("Skipping sync: Google Sheets failed to initialize.")
                return None
            await asyncio.sleep(1)
        
        last_q = state.get("last_assistant_message", "")
        prompt = (
            "Extract the following fields from the customer's reply. Return ONLY STRICT JSON.\n"
            "Identity Fields: name, company_name, job_type, income, current_location, property_location, loan_amount, property_stage.\n"
            "Verification Fields: employment_type (permanent/contract), job_duration (years/months), salary_type (bank/cash), existing_loans, family_details, property_details.\n"
            "Classification: interest_level (HOT/WARM/COLD).\n"
            "\nStrict Rules:\n"
            "1. 'company_name' is the employer. 'job_type' is the role (e.g., Software Engineer, Private Employee).\n"
            "2. 'employment_type' is permanent/contract. 'salary_type' is bank/cash. DO NOT put salary info in 'job_type'.\n"
            "3. ONLY return fields that are explicitly mentioned or clearly implied in the current reply, based on the agent's last question. Omit fields that are not mentioned.\n"
            "4. If the user explicitly states they have NO loans, return 'None' for 'existing_loans'. Otherwise, do not include 'existing_loans' in the JSON.\n"
            "5. If a user mentions their employment status (permanent/contract) but not a role, you can use that for 'job_type' if 'employment_type' is also set.\n"
            "6. 'current_location' = Where they live now. 'property_location' = Where they want to buy property.\n"
            "7. NEVER translate proper nouns like Names or Locations. Keep them as spoken.\n"
            "8. Use English for all other values.\n"
            f"Agent's last question: \"{last_q}\"\n"
            f"Customer's Reply: \"{text}\""
        )

        llm = google.LLM(model=GEMINI_MODEL)
        chat_ctx = ChatContext()
        chat_ctx.add_message(role="user", content=prompt)

        full = ""
        stream = llm.chat(chat_ctx=chat_ctx)
        async for chunk in stream:
            delta = getattr(chunk, "delta", None)
            content = getattr(delta, "content", None) if delta else None
            if content:
                full += content

        extracted = parse_extraction(full)
        if extracted is None:
            logger.info(f"Failed to parse extraction from: {text}")
            return {} # Return empty dict instead of None to signify it ran but found nothing

        logger.info(f"Extracted: {extracted}")

        # Map interest_level to lead_type for backward compatibility
        if "interest_level" in extracted:
            extracted["lead_type"] = extracted["interest_level"]
        elif "lead_type" in extracted:
            extracted["interest_level"] = extracted["lead_type"]

        # Correction logic for shifted or mismatched values
        if "location" in extracted:
            loc_val = str(extracted["location"]).lower()
            if any(x in loc_val for x in ["lakh", "crore", "000"]):
                if not extracted.get("loan_amount"):
                    extracted["loan_amount"] = extracted["location"]
            else:
                # If it's a real location, map it to current_location if not already set
                if not extracted.get("current_location"):
                    extracted["current_location"] = extracted["location"]
            extracted["location"] = ""
            
        # Ensure job_type doesn't contain family or payment info
        for key in ["job_type"]:
            if key in extracted:
                val = str(extracted[key]).lower()
                if any(x in val for x in ["earner", "family", "member", "living"]):
                    if "family" in val and not extracted.get("family_details"):
                        extracted["family_details"] = extracted[key]
                    extracted[key] = None

        # Fallback: If we have employment_type but no job_type, use it to fill the lead sheet
        if extracted.get("employment_type") and not extracted.get("job_type"):
            extracted["job_type"] = extracted["employment_type"]

        if "interest_level" in extracted and extracted["interest_level"] not in ["HOT", "WARM", "COLD"]:
            extracted["interest_level"] = "COLD"

        lead = state["lead"]
        pd = state["pd"]
        pd_updated = False
        for k, v in extracted.items():
            if v is not None and str(v).strip() != "":
                v_str = str(v).strip()
                if k in LEAD_HEADERS:
                    curr = lead.get(k, "")
                    if not curr or curr in ["None", "N/A"] or (v_str != "None" and curr == "None"):
                        lead[k] = v_str
                if k in PD_HEADERS:
                    curr = pd.get(k, "")
                    if not curr or curr in ["None", "N/A"] or (v_str != "None" and curr == "None"):
                        pd[k] = v_str
                        pd_updated = True

        sheets = state.get("sheets")
        await upsert_row(state, "lead_details", lead, LEAD_HEADERS)
        await upsert_row(state, "pd_verification", pd, PD_HEADERS)
        
        # Always trigger PD summary in PD mode if data was updated
        if state.get("mode") == "PD" and pd_updated:
            await generate_and_sync_summary(state)

        # After syncing, return the extracted fields so the agent can check for transition
        return extracted
    except Exception as e:
        logger.exception(f"extract_and_sync failed: {e}")
        return None


async def generate_and_sync_summary(state):
    """Generates a professional English summary of the PD for underwriters."""
    try:
        lead = state["lead"]
        pd = state["pd"]
        
        prompt = (
            "You are an expert mortgage underwriter. Summarize the following customer profile "
            "into a concise 1-paragraph summary in English for a 'Personal Discussion' report. "
            "Focus on employment, stability, and loan intent.\n\n"
            f"LEAD DATA: {json.dumps(lead)}\n"
            f"PD DATA: {json.dumps(pd)}\n"
            "SUMMARY (1 paragraph):"
        )

        llm = google.LLM(model=GEMINI_MODEL)
        chat_ctx = ChatContext()
        chat_ctx.add_message(role="user", content=prompt)

        full = ""
        stream = llm.chat(chat_ctx=chat_ctx)
        async_stream = stream # stream is already an async iterator in this version
        async for chunk in async_stream:
            delta = getattr(chunk, "delta", None)
            content = getattr(delta, "content", None) if delta else None
            if content:
                full += content

        summary = full.strip()
        if summary:
            pd["pd_summary"] = summary
            logger.info(f"Generated Summary for {state.get('call_id')}: {summary}")
            await upsert_row(state, "pd_verification", pd, PD_HEADERS)
        else:
            logger.warning(f"Summary generation returned empty for {state.get('call_id')}")
            
    except Exception as e:
        logger.warning(f"Summary generation failed: {e}")


# ----------------------------------------------------------------------
# Agent
# ----------------------------------------------------------------------
class BhavikAgent(Agent):
    def __init__(self, state):
        super().__init__(
            instructions="""
You are Telugu Bhavik, an AI voice agent for వృద్ధి housing loans.

You operate in TWO MODES:

=====================
MODE 1: SALES AGENT
=====================
Goal:
- Introduce housing loans (14–15%)
- Ask questions step-by-step:
  - Name
  - Company name
  - Monthly income
  - Job type / Role (e.g., Software Engineer, Private Sector Employee)
  - Current location (Where they live now)
  - Property location (Where they want to buy the house)
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

If HOT (user says "now", "immediate", "ఇప్పుడే"):
Say: "మా సీనియర్ టీమ్ మీతో త్వరలో సంప్రదిస్తుంది"
Then MOVE to PD mode.

If COLD:
Politely end conversation.

=====================
MODE 2: PD AGENT
=====================
Goal:
Collect verification details.

Ask:
- Employment type (Permanent/Contract)
- Job duration / tenure (How long working there?)
- Salary type (Is your salary credited to bank or do you receive it in cash?)
- Existing loans
- Family details
- Property details

Final Step:
- Once all details are collected, SUMMARIZE everything back to the user (Name, Income, Job, Locations, Loan, etc.) in natural Telugu and ask if the details are correct.

Rules:
- Be formal
- Ask ONE question at a time
- Do not skip unless details were already provided earlier

=====================
IMPORTANT:
- Start in SALES mode
- If user shows strong intent → switch to PD
- Keep conversation natural
- **PRONUNCIATION RULE**: Always write currency amounts in words (e.g., "నలభై వేల రూపాయలు" or "forty thousand rupees") instead of digits (e.g., "40,000") so they are spoken naturally.
- **PROPER NOUNS**: Use Telugu script for English company names and locations (e.g., 'క్యాప్‌జెమిని' for Capgemini, 'హైటెక్ సిటీ' for Hi-Tech City) to ensure the voice engine pronounces them correctly.
- **ANTI-REPETITION**: Do not repeat the user's answer multiple times. Acknowledge once and move to the next question immediately.
""",
            stt=sarvam.STT(language="te-IN", model="saaras:v2.5"),
            llm=google.LLM(model=GEMINI_MODEL),
            tts=sarvam.TTS(target_language_code="te-IN", model="bulbul:v2", speaker="abhilash"),
            vad=silero.VAD.load(),
        )
        self.state = state

    async def _check_mode_transition(self, text=""):
        """Check if all sales fields are collected or if user showed strong intent (HOT)."""
        if self.state.get("mode") == "PD":
            return

        lead = self.state["lead"]
        text_lower = text.lower()
        
        # KEYWORD-BASED TRANSITION (From your reference)
        is_hot = any(w in text_lower for w in ["ఇప్పుడే", "now", "immediate", "urgent"])
        
        # DATA-BASED TRANSITION
        required = ["name", "company_name", "income", "job_type", "current_location", "property_location", "loan_amount", "property_stage"]
        missing = [f for f in required if not lead.get(f)]
        
        if is_hot or not missing:
            self.state["mode"] = "PD"
            logger.info(f"--- MODE TRANSITION: SALES -> PD (Reason: {'HOT' if is_hot else 'DATA'}) ---")
            
            # Update the agent's internal instructions by modifying the chat context
            # Calculate missing sales fields to ask in PD mode
            missing_sales = [f.replace("_", " ") for f in required if not lead.get(f)]
            missing_instr_fragment = f"\nFirst, ensure we have these missing details: {', '.join(missing_sales)}." if missing_sales else ""

            new_instr = f"""
User is now in PD (Personal Discussion) mode.
If they were a HOT lead, start by saying: "మా సీనియర్ టీమ్ మీతో త్వరలో సంప్రదిస్తుంది"
{missing_instr_fragment}

Now ask verification details step-by-step:
- Employment type (Permanent/Contract)
- Job duration (How long in current company?)
- Salary type (Is your salary credited to bank or do you receive it in cash?)
- Existing loans
- Family details
- Property details

After all verification is done, provide a clear SUMMARY of everything we collected (Name, Income, Job, Locations, Loan, Family info) and ask: "ఈ వివరాలన్నీ సరైనవేనా?" (Are all these details correct?). 
**Note**: Mention all amounts in words (e.g., "నలభై వేల రూపాయలు") and use Telugu script for any English names for natural pronunciation.

Stay friendly and conversational in Telugu.
"""
            if self.chat_ctx:
                try:
                    ctx = self.chat_ctx.copy()
                    # Check if messages is a method or a property
                    msgs = ctx.messages() if callable(ctx.messages) else ctx.messages
                    if msgs:
                        msgs[0].content = new_instr
                        if hasattr(self, "update_chat_ctx"):
                            self.update_chat_ctx(ctx)
                        else:
                            logger.warning("Agent missing update_chat_ctx method")
                except Exception as e:
                    logger.warning(f"Failed to update chat context in mode transition: {e}")
            
            # Log the mode change to Google Sheets
            sheets = self.state.get("sheets")
            if sheets:
                asyncio.create_task(
                    append_call_log(self.state, "PD", lead.get("lead_type", "COLD"), "In Progress")
                )
        else:
            logger.info(f"Still in SALES mode. Waiting for: {missing}")

    async def safe_reply(self, text):
        """Helper to speak a fixed string safely."""
        try:
            await self.session.say(text, allow_interruptions=True)
        except Exception as e:
            logger.warning(f"safe_reply failed: {e}")

    async def on_enter(self):
        if self.state.get("greeted"):
            logger.info("on_enter called but already greeted, skipping.")
            return
        self.state["greeted"] = True
        
        print("--- BHAVIK ENTERED ROOM ---")
        logger.info(f"--- BHAVIK ENTERED ROOM (Call ID: {self.state['call_id']}) ---")
        
        greeting = "నమస్తే! వృద్ధి హౌసింగ్ లోన్స్ నుంచి మాట్లాడుతున్నాను. మా లోన్స్ సుమారు పద్నాలుగు నుండి పదిహేను శాతం వడ్డీతో ఉంటాయి. మీ పేరు చెప్పండి."
        
        # Add to chat context so the LLM knows it has already greeted the user
        if self.chat_ctx:
            try:
                # Based on the error: use .copy() and update_chat_ctx()
                ctx = self.chat_ctx.copy()
                ctx.add_message(role="assistant", content=greeting)
                # Some versions use update_chat_ctx, others might just allow assigning if it's a property
                if hasattr(self, "update_chat_ctx"):
                    self.update_chat_ctx(ctx)
                else:
                    # Fallback for other versions
                    self.chat_ctx.messages.append(ctx.messages[-1])
            except Exception as ctx_err:
                logger.warning(f"Failed to update chat context: {ctx_err}")
            
        await self.safe_reply(greeting)
        print("--- GREETING TRIGGERED ---")
        logger.info("Greeting generation triggered")

    async def on_user_turn_completed(self, turn_ctx, new_message):
        print("USER TURN TRIGGERED")
        text = ""
        try:
            text = (getattr(new_message, "text_content", None)
                    or getattr(new_message, "content", None)
                    or "")
            if isinstance(text, list):
                text = " ".join(str(p) for p in text)
            text = str(text).strip()
        except Exception:
            text = ""
        if not text:
            return

        logger.info(f"USER: {text}")
        asyncio.create_task(append_transcript(self.state, "user", text))
        
        # Run extraction and transition check in the BACKGROUND to avoid delay
        async def background_logic():
            await extract_and_sync(self.state, text)
            await self._check_mode_transition(text)

        asyncio.create_task(background_logic())

        # CRITICAL: Call super to trigger automatic reply generation IMMEDIATELY
        await super().on_user_turn_completed(turn_ctx, new_message)


# ----------------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------------
async def entrypoint(ctx: JobContext):
    print(f"--- ENTRYPOINT TRIGGERED FOR ROOM: {ctx.room.name} ---")
    logger.info(f"--- Entrypoint called for Room: {ctx.room.name} ---")
    try:
        await ctx.connect()
        logger.info(f"--- Connected to Room: {ctx.room.name} ---")

        logger.info("--- Waiting for participant ---")
        participant = await ctx.wait_for_participant()
        logger.info(f"--- Participant joined: {participant.identity} ---")
    except Exception as e:
        logger.error(f"Failed to establish session: {e}")
        return
    logger.info(f"--- Participant joined ({participant.identity}), starting agent ---")

    call_id = str(uuid.uuid4())[:8]
    state = {
        "call_id": call_id,
        "sheets": None,
        "lead": {"call_id": call_id},
        "pd": {"call_id": call_id},
        "mode": "SALES",
        "lock": asyncio.Lock(),
    }

    async def load_sheets():
        sheets = await asyncio.to_thread(init_google_sheets)
        if sheets:
            state["sheets"] = sheets
            logger.info("Google Sheets initialized successfully")
            sync_headers(state) # Automatically update column names in Row 1
            await append_call_log(state, "SALES", "COLD", "Started")
        else:
            state["sheets_failed"] = True
            logger.error("Failed to initialize Google Sheets. Check your credentials and SHEET_NAME.")

    # Load sheets synchronously BEFORE starting
    await load_sheets()

    agent = BhavikAgent(state)
    session = AgentSession()

    @session.on("conversation_item_added")
    def _on_item(ev):
        try:
            item = getattr(ev, "item", None)
            if item is None:
                return
            role = getattr(item, "role", None)
            text = (getattr(item, "text_content", None)
                    or getattr(item, "content", None))
            if isinstance(text, list):
                text = " ".join(str(p) for p in text)
            if role == "assistant" and text:
                logger.info(f"BHAVIK: {text}")
                state["last_assistant_message"] = str(text)
                asyncio.create_task(
                    append_transcript(state, "assistant", str(text))
                )
        except Exception as e:
            logger.exception(f"transcript hook err: {e}")

    await session.start(agent=agent, room=ctx.room)
    print("--- SESSION STARTED ---")
    logger.info("Agent session is live")

    # Trigger the greeting immediately after starting the session
    asyncio.create_task(agent.on_enter())


if __name__ == "__main__":
    http_port = int(os.environ.get("AGENT_HTTP_PORT", "0"))
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            port=http_port,
            agent_name="telugu-bhavik",
            num_idle_processes=1,
            load_threshold=1.5,
        )
    )
