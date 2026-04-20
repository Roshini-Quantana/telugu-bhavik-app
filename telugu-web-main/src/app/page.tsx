"use client";

import { useState, useCallback } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useVoiceAssistant,
  BarVisualizer,
  useRoomContext,
} from "@livekit/components-react";
import "@livekit/components-styles";

// ── Shared full-screen wrapper — keeps card centered always ─────────────────
function PageWrapper({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      minHeight: "100vh",
      width: "100%",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "radial-gradient(ellipse at 60% 0%, #1e0a3c 0%, #0d0d1a 60%)",
      fontFamily: "'Segoe UI', system-ui, sans-serif",
      color: "#f0e6ff",
    }}>
      {children}
    </div>
  );
}

// ── Agent card (inside LiveKitRoom) ─────────────────────────────────────────
function AgentUI({ onDisconnect }: { onDisconnect: () => void }) {
  const { state: agentState, audioTrack } = useVoiceAssistant();

  const stateLabel: Record<string, string> = {
    disconnected: "Disconnected",
    connecting: "Connecting…",
    initializing: "Initializing…",
    listening: "🎤 Listening…",
    thinking: "🧠 Thinking…",
    speaking: "🔊 Speaking…",
  };

  return (
    <div style={cardStyle}>
      <h1 style={titleStyle}>Telugu Bhavik 🎙️</h1>
      <p style={subtitleStyle}>Your AI Telugu Voice Assistant powered by LiveKit &amp; Sarvam</p>

      <div style={vizWrapStyle}>
        <BarVisualizer
          state={agentState}
          trackRef={audioTrack}
          barCount={24}
          style={{ width: "100%", height: "64px" }}
        />
      </div>

      <div style={pillStyle}>
        <span style={{
          ...dotBase,
          background: dotColor[agentState] ?? "#6b7280",
          animation: animating.includes(agentState) ? "pulse 1s infinite" : "none",
        }} />
        {stateLabel[agentState] ?? agentState}
      </div>

      <button
        onClick={onDisconnect}
        style={{ ...btnStyle, background: "linear-gradient(135deg, #dc2626, #ef4444)" }}
      >
        Disconnect
      </button>

      <RoomAudioRenderer />

      <style>{`
        @keyframes pulse {
          0%,100% { opacity:1; transform:scale(1); }
          50%      { opacity:0.5; transform:scale(1.4); }
        }
      `}</style>
    </div>
  );
}

// ── Root ────────────────────────────────────────────────────────────────────
export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [wsUrl, setWsUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "fetching" | "connected" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const connect = useCallback(async () => {
    try {
      setStatus("fetching");
      setErrorMsg("");
      const res = await fetch("/api/livekit/token");
      if (!res.ok) throw new Error(`Token fetch failed: ${res.status}`);
      const data = await res.json();
      if (!data.token || !data.url) throw new Error("Invalid token/URL from server");
      setToken(data.token);
      setWsUrl(data.url);
      setStatus("connected");
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Unknown error");
      setStatus("error");
    }
  }, []);

  const handleDisconnected = useCallback(() => {
    setToken(null);
    setWsUrl(null);
    setStatus("idle");
  }, []);

  if (status === "connected" && token && wsUrl) {
    return (
      // ✅ Wrap LiveKitRoom in our own centering div
      <PageWrapper>
        <LiveKitRoom
          token={token}
          serverUrl={wsUrl}
          connect={true}
          audio={true}
          video={false}
          onDisconnected={handleDisconnected}
          style={{ display: "contents" }} // ← makes LiveKitRoom's div invisible to layout
        >
          <AgentUI onDisconnect={handleDisconnected} />
        </LiveKitRoom>
      </PageWrapper>
    );
  }

  return (
    <PageWrapper>
      <div style={cardStyle}>
        <h1 style={titleStyle}>Telugu Bhavik 🎙️</h1>
        <p style={subtitleStyle}>Your AI Telugu Voice Assistant powered by LiveKit &amp; Sarvam</p>

        <div style={micRingStyle}>🎤</div>

        {status === "error" && (
          <div style={errorBoxStyle}>⚠️ {errorMsg}</div>
        )}

        <button
          onClick={connect}
          disabled={status === "fetching"}
          style={{
            ...btnStyle,
            background: "linear-gradient(135deg, #7c3aed, #a855f7)",
            opacity: status === "fetching" ? 0.6 : 1,
            cursor: status === "fetching" ? "not-allowed" : "pointer",
          }}
        >
          {status === "fetching" ? "Connecting…" : "Connect & Talk"}
        </button>
      </div>
    </PageWrapper>
  );
}

// ── Styles ──────────────────────────────────────────────────────────────────
const cardStyle: React.CSSProperties = {
  background: "rgba(255,255,255,0.06)",
  backdropFilter: "blur(24px)",
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: "28px",
  padding: "2.5rem 2rem",
  width: "min(420px, 92vw)",
  textAlign: "center",
  boxShadow: "0 24px 80px rgba(0,0,0,0.5)",
  display: "flex",
  flexDirection: "column",
  gap: "1.25rem",
};

const titleStyle: React.CSSProperties = {
  fontSize: "2rem",
  fontWeight: 800,
  background: "linear-gradient(135deg, #c084fc, #f472b6)",
  WebkitBackgroundClip: "text",
  WebkitTextFillColor: "transparent",
  backgroundClip: "text",
  letterSpacing: "-0.5px",
  margin: 0,
};

const subtitleStyle: React.CSSProperties = {
  color: "#a78bbb",
  fontSize: "0.9rem",
  lineHeight: 1.5,
  margin: 0,
};

const vizWrapStyle: React.CSSProperties = {
  background: "rgba(0,0,0,0.25)",
  borderRadius: "16px",
  padding: "1rem",
  border: "1px solid rgba(255,255,255,0.07)",
};

const pillStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "0.5rem",
  background: "rgba(255,255,255,0.08)",
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: "999px",
  padding: "0.4rem 1rem",
  fontSize: "0.82rem",
  fontWeight: 500,
  alignSelf: "center",
};

const dotBase: React.CSSProperties = {
  width: "9px",
  height: "9px",
  borderRadius: "50%",
  flexShrink: 0,
  display: "inline-block",
};

const dotColor: Record<string, string> = {
  listening: "#22c55e",
  speaking: "#a855f7",
  thinking: "#f59e0b",
  connecting: "#60a5fa",
  initializing: "#60a5fa",
};

const animating = ["listening", "speaking", "thinking", "connecting", "initializing"];

const btnStyle: React.CSSProperties = {
  width: "100%",
  padding: "0.85rem 1.5rem",
  border: "none",
  borderRadius: "14px",
  fontSize: "1rem",
  fontWeight: 700,
  cursor: "pointer",
  color: "#fff",
  transition: "filter 0.2s, transform 0.1s",
};

const micRingStyle: React.CSSProperties = {
  width: "72px",
  height: "72px",
  margin: "0.5rem auto",
  borderRadius: "50%",
  background: "linear-gradient(135deg, #7c3aed33, #a855f733)",
  border: "2px solid rgba(168,85,247,0.4)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: "2rem",
};

const errorBoxStyle: React.CSSProperties = {
  background: "rgba(220,38,38,0.15)",
  border: "1px solid rgba(220,38,38,0.4)",
  borderRadius: "12px",
  padding: "0.75rem 1rem",
  fontSize: "0.82rem",
  color: "#fca5a5",
};