/* Speech in and out. Recording is 16 kHz mono WAV made in the browser, which is what the
   transcription endpoint expects; speaking uses the browser's own speech synthesis. */

import { api } from "./api";
import { speakable } from "./format";

type Recording = { stream: MediaStream; ctx: AudioContext; node: ScriptProcessorNode; chunks: Float32Array[] };

function wav(samples: Float32Array, rate: number): Blob {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const w = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  w(8, "WAVE");
  w(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  w(36, "data");
  v.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([buf], { type: "audio/wav" });
}

function downsample(chunks: Float32Array[], from: number, to: number): Float32Array {
  const all = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let o = 0;
  for (const c of chunks) {
    all.set(c, o);
    o += c.length;
  }
  const ratio = from / to;
  const out = new Float32Array(Math.floor(all.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(all.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += all[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

export class Recorder {
  private rec: Recording | null = null;

  get active() {
    return this.rec !== null;
  }

  async start() {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(stream);
    const node = ctx.createScriptProcessor(4096, 1, 1);
    const chunks: Float32Array[] = [];
    node.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    source.connect(node);
    node.connect(ctx.destination);
    this.rec = { stream, ctx, node, chunks };
  }

  async stop(): Promise<Blob> {
    const r = this.rec;
    this.rec = null;
    if (!r) throw new Error("Not recording.");
    r.node.disconnect();
    r.stream.getTracks().forEach((t) => t.stop());
    const rate = r.ctx.sampleRate;
    await r.ctx.close();
    return wav(downsample(r.chunks, rate, 16000), 16000);
  }
}

export async function transcribe(blob: Blob, languages: string): Promise<{ text: string; seconds: number }> {
  const form = new FormData();
  form.append("audio", blob, "speech.wav");
  form.append("languages", languages);
  return api("/api/voice", { method: "POST", form });
}

/** Every language the assistant understands, as the transcription hint when nobody chose one. */
export const ANY_LANGUAGE = "English,Hindi,Telugu";

/** The language a text is written in, from its script: Telugu, Devanagari (Hindi), or English. */
export function langOf(text: string): "te-IN" | "hi-IN" | "en-IN" {
  const telugu = (text.match(/[\u0C00-\u0C7F]/g) ?? []).length;
  const hindi = (text.match(/[\u0900-\u097F]/g) ?? []).length;
  if (telugu > 8 && telugu >= hindi) return "te-IN";
  if (hindi > 8) return "hi-IN";
  return "en-IN";
}

function voices(): Promise<SpeechSynthesisVoice[]> {
  const now = speechSynthesis.getVoices();
  if (now.length) return Promise.resolve(now);
  return new Promise((done) => {
    const t = setTimeout(() => done(speechSynthesis.getVoices()), 1200);
    speechSynthesis.addEventListener(
      "voiceschanged",
      () => {
        clearTimeout(t);
        done(speechSynthesis.getVoices());
      },
      { once: true },
    );
  });
}

/** A voice that speaks the language natively: never an English voice reading Hindi or Telugu.
 * Prefers the higher quality network voices browsers offer (Google, Microsoft "Online"). */
async function voiceFor(lang: string): Promise<SpeechSynthesisVoice | undefined> {
  const all = await voices();
  const norm = (v: SpeechSynthesisVoice) => v.lang.replace("_", "-").toLowerCase();
  const exact = all.filter((v) => norm(v) === lang.toLowerCase());
  const family = all.filter((v) => norm(v).startsWith(lang.slice(0, 2).toLowerCase()));
  const pool = exact.length ? exact : family;
  const good = (v: SpeechSynthesisVoice) => /google|online|natural|neural/i.test(v.name);
  return pool.find(good) ?? pool[0];
}

/** Long answers are spoken a sentence at a time: browsers cut a single long utterance short. */
function pieces(text: string): string[] {
  return (text.match(/[^.!?।\n]+[.!?।]?/g) ?? [text]).map((p) => p.trim()).filter(Boolean);
}

/** Speak ``text`` in its own language, found from its script: an English notice always sounds
 * English, a Telugu answer is read by a Telugu voice. */
export async function say(text: string, { rate = 1 }: { rate?: number } = {}): Promise<void> {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  const clean = speakable(text);
  const lang = langOf(clean);
  const voice = await voiceFor(lang);
  await new Promise<void>((done) => {
    const parts = pieces(clean);
    parts.forEach((part, i) => {
      const u = new SpeechSynthesisUtterance(part);
      u.lang = voice?.lang ?? lang;
      if (voice) u.voice = voice;
      u.rate = rate;
      if (i === parts.length - 1) {
        u.onend = () => done();
        u.onerror = () => done();
      }
      speechSynthesis.speak(u);
    });
    if (!parts.length) done();
  });
}

/** Whether this browser has a voice for ``lang`` at all (Telugu often needs one installed). */
export async function hasVoice(lang: string): Promise<boolean> {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return false;
  return (await voiceFor(lang)) !== undefined;
}
