import { AccessToken, AgentDispatchClient } from "livekit-server-sdk";
import { NextResponse } from "next/server";

const ROOM_NAME = "telugu-room";
const AGENT_NAME = "telugu-bhavik";

export async function GET() {
    const apiKey = process.env.LIVEKIT_API_KEY;
    const apiSecret = process.env.LIVEKIT_API_SECRET;
    const wsUrl = process.env.LIVEKIT_URL;

    if (!apiKey || !apiSecret || !wsUrl) {
        console.error("Missing env vars:", { apiKey: !!apiKey, apiSecret: !!apiSecret, wsUrl: !!wsUrl });
        return NextResponse.json(
            { error: "Server misconfigured - missing env vars" },
            { status: 500 }
        );
    }

    const identity = `user-${Math.random().toString(36).slice(2, 9)}`;
    const roomName = `${ROOM_NAME}-${Math.random().toString(36).slice(2, 9)}`;

    const token = new AccessToken(apiKey, apiSecret, {
        identity,
        ttl: "1h",
    });

    token.addGrant({
        roomJoin: true,
        room: roomName,
        canPublish: true,
        canSubscribe: true,
        canPublishData: true,
    });

    const jwt = await token.toJwt();

    try {
        const dispatchClient = new AgentDispatchClient(wsUrl, apiKey, apiSecret);
        const dispatch = await dispatchClient.createDispatch(roomName, AGENT_NAME, {});
        console.log("Dispatched agent:", AGENT_NAME, "to room:", roomName, "dispatchId:", dispatch.id);
    } catch (err) {
        console.error("Failed to dispatch agent:", err);
        return NextResponse.json(
            { error: "Failed to dispatch agent" },
            { status: 500 }
        );
    }

    console.log("Generated token for:", identity, "room:", roomName);

    return NextResponse.json({
        token: jwt,
        url: wsUrl,
    });
}