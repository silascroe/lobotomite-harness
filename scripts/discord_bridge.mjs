#!/usr/bin/env node

/**
 * Bridge one paired Discord server channel to the local Agent Lab session.
 *
 * This intentionally uses Node's built-in fetch and WebSocket APIs. The
 * Discord bot token is supplied through the environment by the PowerShell
 * runner and is never written to the repository or bridge state.
 */

import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const STATE_PATH = path.join(ROOT, "agent-lab", "discord-bridge-state.json");
const LOCAL_API = "http://127.0.0.1:8787";
const DISCORD_API = "https://discord.com/api/v10";
const TOKEN_ENV = "LLMTESTING_DISCORD_BOT_TOKEN";
const MAX_DISCORD_MESSAGE = 1900;
const REPLY_TIMEOUT_MS = 5 * 60 * 1000;
const POLL_INTERVAL_MS = 500;

const INTENTS =
  (1 << 0) | // GUILDS
  (1 << 9) | // GUILD_MESSAGES
  (1 << 12) | // DIRECT_MESSAGES
  (1 << 15); // MESSAGE_CONTENT

let state = null;
let botUser = null;
let socket = null;
let heartbeatTimer = null;
let reconnectTimer = null;
let reconnectAttempt = 0;
let sequence = null;
let shuttingDown = false;
let pairingCode = newPairingCode();
const activeChannels = new Set();

function newPairingCode() {
  return String(Math.floor(100000 + Math.random() * 900000));
}

function tokenValue() {
  const token = process.env[TOKEN_ENV]?.trim();
  if (!token) {
    throw new Error(`${TOKEN_ENV} is missing. Run scripts\\start-discord-bridge.ps1 and enter the token when prompted.`);
  }
  return token;
}

function redact(value) {
  const token = process.env[TOKEN_ENV]?.trim();
  const text = String(value);
  return token ? text.split(token).join("<redacted>") : text;
}

function initialState() {
  return {
    version: 1,
    authorized_user_id: null,
    authorized_guild_id: null,
    authorized_channel_id: null,
    sessions: {},
  };
}

async function loadState() {
  if (!existsSync(STATE_PATH)) return initialState();
  try {
    const value = JSON.parse(await readFile(STATE_PATH, "utf8"));
    if (!value || typeof value !== "object") return initialState();
    return {
      ...initialState(),
      ...value,
      sessions: value.sessions && typeof value.sessions === "object" ? value.sessions : {},
    };
  } catch (error) {
    throw new Error(`could not read ${STATE_PATH}: ${redact(error.message)}`);
  }
}

async function saveState() {
  await mkdir(path.dirname(STATE_PATH), { recursive: true });
  await writeFile(STATE_PATH, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}

async function requestJson(url, { method = "GET", headers = {}, body, timeoutMs = 30000 } = {}) {
  const requestHeaders = { ...headers };
  const options = { method, headers: requestHeaders, signal: AbortSignal.timeout(timeoutMs) };
  if (body !== undefined) {
    requestHeaders["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error(`request failed for ${url}: ${redact(error.message)}`);
  }

  const raw = await response.text();
  let value = {};
  if (raw) {
    try {
      value = JSON.parse(raw);
    } catch {
      value = { raw: raw.slice(0, 500) };
    }
  }
  if (!response.ok) {
    const detail = value?.message || value?.error || value?.raw || `${response.status} ${response.statusText}`;
    throw new Error(`${response.status} from ${url}: ${redact(detail)}`);
  }
  return value;
}

async function discordRequest(endpoint, method = "GET", body) {
  return requestJson(`${DISCORD_API}${endpoint}`, {
    method,
    body,
    timeoutMs: 40000,
    headers: { Authorization: `Bot ${tokenValue()}` },
  });
}

async function localRequest(endpoint, body) {
  return requestJson(`${LOCAL_API}${endpoint}`, {
    method: body === undefined ? "GET" : "POST",
    body,
    timeoutMs: body === undefined ? 30000 : 40000,
  });
}

function splitMessage(text) {
  const normalized = String(text || "").trim() || "(empty response)";
  const chunks = [];
  for (let start = 0; start < normalized.length; start += MAX_DISCORD_MESSAGE) {
    chunks.push(normalized.slice(start, start + MAX_DISCORD_MESSAGE));
  }
  return chunks;
}

async function sendDiscordMessage(channelId, text) {
  return discordRequest(`/channels/${channelId}/messages`, "POST", {
    content: splitMessage(text)[0],
    allowed_mentions: { parse: [] },
  });
}

async function sendLongReply(channelId, text, placeholderId = null) {
  const chunks = splitMessage(text);
  if (placeholderId) {
    await discordRequest(`/channels/${channelId}/messages/${placeholderId}`, "PATCH", {
      content: chunks[0],
      allowed_mentions: { parse: [] },
    });
  } else {
    await sendDiscordMessage(channelId, chunks[0]);
  }
  for (const chunk of chunks.slice(1)) {
    await discordRequest(`/channels/${channelId}/messages`, "POST", {
      content: chunk,
      allowed_mentions: { parse: [] },
    });
  }
}

async function sendTyping(channelId) {
  try {
    await discordRequest(`/channels/${channelId}/typing`, "POST");
  } catch (error) {
    console.error(`Typing indicator failed: ${redact(error.message)}`);
  }
}

function sessionPath(sessionId, suffix = "") {
  return `/api/sessions/${encodeURIComponent(sessionId)}${suffix}`;
}

async function createAgentSession() {
  const result = await localRequest("/api/sessions", {});
  if (!result || typeof result.session_id !== "string" || !result.session_id) {
    throw new Error("Agent Lab did not return a session id");
  }
  return result.session_id;
}

async function getAgentSession(sessionId) {
  return localRequest(sessionPath(sessionId));
}

async function ensureAgentSession(channelId) {
  const existing = state.sessions[channelId];
  if (typeof existing === "string" && existing) {
    try {
      await getAgentSession(existing);
      return existing;
    } catch {
      // The UI server may have restarted and forgotten its in-memory session.
    }
  }
  const sessionId = await createAgentSession();
  state.sessions[channelId] = sessionId;
  await saveState();
  return sessionId;
}

async function resetAgentSession(channelId) {
  const sessionId = await createAgentSession();
  state.sessions[channelId] = sessionId;
  await saveState();
  return sessionId;
}

async function waitForAgentReply(sessionId, previousCount) {
  const deadline = Date.now() + REPLY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    const current = await getAgentSession(sessionId);
    if (current.status === "error") {
      throw new Error(current.last_error || "Agent Lab session failed");
    }
    const conversation = Array.isArray(current.conversation) ? current.conversation : [];
    if (!current.busy && conversation.length > previousCount) {
      for (let index = conversation.length - 1; index >= previousCount; index -= 1) {
        const message = conversation[index];
        if (message?.role === "assistant" && String(message.content || "").trim()) {
          return String(message.content).trim();
        }
      }
      throw new Error("Agent Lab finished without an assistant response");
    }
  }
  throw new Error("Agent Lab did not finish within five minutes");
}

async function askAgent(channelId, content) {
  const sessionId = await ensureAgentSession(channelId);
  const before = await getAgentSession(sessionId);
  const previousCount = Array.isArray(before.conversation) ? before.conversation.length : 0;
  await localRequest(sessionPath(sessionId, "/messages"), { content });
  return waitForAgentReply(sessionId, previousCount);
}

function stripBotMention(content) {
  if (!botUser?.id) return content.trim();
  return content
    .replace(new RegExp(`<@!?${botUser.id}>`, "g"), "")
    .trim();
}

function isPairedMessage(message) {
  return (
    message.author?.id === state.authorized_user_id &&
    message.guild_id === state.authorized_guild_id &&
    message.channel_id === state.authorized_channel_id
  );
}

async function pairMessage(message) {
  const content = String(message.content || "").trim();
  if (content !== `!pair ${pairingCode}`) return false;
  if (!message.guild_id) {
    await sendDiscordMessage(message.channel_id, "Pairing must happen in a server channel, not a DM.");
    return true;
  }
  state.authorized_user_id = message.author.id;
  state.authorized_guild_id = message.guild_id;
  state.authorized_channel_id = message.channel_id;
  state.sessions = {};
  await saveState();
  await sendDiscordMessage(
    message.channel_id,
    "Paired. This channel now controls your local Agent Lab. Send a prompt, `!status`, `!reasoning deep`, or `!reset`.",
  );
  console.log(`Paired Discord user ${message.author.id} to guild ${message.guild_id}, channel ${message.channel_id}.`);
  return true;
}

async function commandResponse(channelId, content) {
  const parts = content.split(/\s+/);
  const command = parts[0].toLowerCase();
  if (command === "!help") {
    return "Commands: `!status`, `!reset`, `!reasoning off|low|standard|deep|max`, or send a normal prompt.";
  }
  if (command === "!reset") {
    const sessionId = await resetAgentSession(channelId);
    return `Started a fresh Agent Lab conversation (${sessionId}).`;
  }
  if (command === "!status") {
    const sessionId = await ensureAgentSession(channelId);
    const current = await getAgentSession(sessionId);
    return `Agent Lab is ${current.status || "unknown"}; model: ${current.model || "local model"}; reasoning: ${current.reasoning_level || "standard"}; model calls: ${current.model_calls || 0}.`;
  }
  if (command === "!reasoning") {
    const level = (parts[1] || "").toLowerCase();
    const allowed = new Set(["off", "low", "standard", "deep", "max"]);
    if (!allowed.has(level)) return "Use `!reasoning off`, `low`, `standard`, `deep`, or `max`.";
    const sessionId = await ensureAgentSession(channelId);
    await localRequest(sessionPath(sessionId, "/settings"), { reasoning_level: level });
    return `Reasoning set to ${level}.`;
  }
  return null;
}

async function handleMessage(message) {
  if (!message?.author || message.author.bot || typeof message.content !== "string") return;
  if (!state.authorized_user_id) {
    await pairMessage(message);
    return;
  }
  if (!isPairedMessage(message)) return;

  const channelId = message.channel_id;
  if (activeChannels.has(channelId)) {
    await sendDiscordMessage(channelId, "I’m still working on the previous message in this channel.");
    return;
  }

  const content = stripBotMention(message.content);
  if (!content) return;
  activeChannels.add(channelId);
  try {
    const command = await commandResponse(channelId, content);
    if (command) {
      await sendLongReply(channelId, command);
      return;
    }
    await sendTyping(channelId);
    const placeholder = await sendDiscordMessage(channelId, "Working…");
    try {
      const reply = await askAgent(channelId, content);
      await sendLongReply(channelId, reply, placeholder?.id || null);
    } catch (error) {
      await sendLongReply(channelId, `Local Agent Lab error: ${redact(error.message)}`, placeholder?.id || null);
    }
  } finally {
    activeChannels.delete(channelId);
  }
}

function sendGateway(payload) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify(payload));
}

function stopHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

function startHeartbeat(intervalMs) {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => sendGateway({ op: 1, d: sequence }), intervalMs);
}

function scheduleReconnect() {
  if (shuttingDown || reconnectTimer) return;
  const delay = Math.min(30000, 1000 * 2 ** Math.min(reconnectAttempt, 5));
  reconnectAttempt += 1;
  console.log(`Discord disconnected; reconnecting in ${Math.ceil(delay / 1000)}s.`);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void connectGateway();
  }, delay);
}

async function gatewayUrl() {
  const result = await discordRequest("/gateway/bot");
  if (!result?.url) throw new Error("Discord did not return a Gateway URL");
  return `${result.url}?v=10&encoding=json`;
}

async function connectGateway() {
  if (shuttingDown) return;
  let url;
  try {
    url = await gatewayUrl();
  } catch (error) {
    console.error(`Discord connection setup failed: ${redact(error.message)}`);
    scheduleReconnect();
    return;
  }

  const nextSocket = new WebSocket(url);
  socket = nextSocket;
  nextSocket.addEventListener("open", () => {
    console.log("Connected to the Discord Gateway; waiting for READY.");
  });
  nextSocket.addEventListener("message", (event) => {
    let packet;
    try {
      packet = JSON.parse(String(event.data));
    } catch (error) {
      console.error(`Invalid Discord Gateway packet: ${redact(error.message)}`);
      return;
    }
    sequence = packet.s ?? sequence;
    void handleGatewayPacket(packet).catch((error) => {
      console.error(`Gateway event failed: ${redact(error.message)}`);
    });
  });
  nextSocket.addEventListener("error", (event) => {
    console.error(`Discord WebSocket error: ${redact(event.error?.message || "connection error")}`);
  });
  nextSocket.addEventListener("close", (event) => {
    if (socket !== nextSocket) return;
    socket = null;
    stopHeartbeat();
    if (event.code === 4004 || event.code === 4013 || event.code === 4014) {
      shuttingDown = true;
      console.error(`Discord closed the connection with code ${event.code}. Check the token and enabled Gateway Intents.`);
      return;
    }
    scheduleReconnect();
  });
}

async function handleGatewayPacket(packet) {
  if (packet.op === 10) {
    startHeartbeat(packet.d.heartbeat_interval);
    sendGateway({
      op: 2,
      d: {
        token: tokenValue(),
        intents: INTENTS,
        properties: { os: "windows", browser: "agent-lab-discord-bridge", device: "agent-lab-discord-bridge" },
      },
    });
    return;
  }
  if (packet.op === 1) {
    sendGateway({ op: 1, d: sequence });
    return;
  }
  if (packet.op === 7 || packet.op === 9) {
    socket?.close();
    return;
  }
  if (packet.op !== 0) return;

  if (packet.t === "READY") {
    botUser = packet.d.user;
    reconnectAttempt = 0;
    console.log(`Discord bot online as ${botUser.username || botUser.id}.`);
    if (!state.authorized_user_id) {
      console.log(`Pairing required. In the target server channel, send: !pair ${pairingCode}`);
    } else {
      console.log(`Discord bridge is paired to channel ${state.authorized_channel_id}.`);
    }
    return;
  }
  if (packet.t === "MESSAGE_CREATE") {
    await handleMessage(packet.d);
  }
}

async function main() {
  if (process.argv.includes("--check")) {
    console.log("Discord bridge source is valid.");
    return;
  }
  tokenValue();
  if (typeof WebSocket !== "function" || typeof fetch !== "function") {
    throw new Error("This bridge requires Node 22 or newer with built-in fetch and WebSocket support.");
  }
  state = await loadState();
  console.log("Starting the local Discord bridge. Press Ctrl+C to stop it.");
  await connectGateway();
}

async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  stopHeartbeat();
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
  socket?.close(1000, signal);
  console.log(`\nDiscord bridge stopped (${signal}).`);
}

process.on("SIGINT", () => void shutdown("SIGINT"));
process.on("SIGTERM", () => void shutdown("SIGTERM"));

main().catch((error) => {
  console.error(`Discord bridge failed: ${redact(error.message)}`);
  process.exitCode = 1;
});

