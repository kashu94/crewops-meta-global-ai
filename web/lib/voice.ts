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

export const LANGUAGES = [
  { value: "English", label: "English" },
  { value: "Hindi,English", label: "Hindi" },
  { value: "Telugu,English", label: "Telugu" },
  { value: "Hindi,Telugu,English", label: "Mixed" },
];

export function say(text: string, languages = "English", rate = 1): Promise<void> {
  return new Promise((done) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return done();
    const u = new SpeechSynthesisUtterance(speakable(text));
    const lang = languages.split(",")[0];
    u.lang = lang === "Hindi" ? "hi-IN" : lang === "Telugu" ? "te-IN" : "en-IN";
    u.rate = rate;
    u.onend = () => done();
    u.onerror = () => done();
    speechSynthesis.speak(u);
  });
}
