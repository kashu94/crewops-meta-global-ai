"use client";

import { Camera, ChevronDown, ImageUp } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, message } from "@/lib/api";

import { Button, control, cx, Input, Label, Notice, Pill, Spinner } from "./ui";

type Box = { x1: number; y1: number; x2: number; y2: number; width: number; height: number; confidence: number };
type Intake = {
  status: "rejected" | "reshoot" | "confirm" | "draft";
  message: string;
  confidence?: string;
  quality?: { width: number; height: number; sharpness: number; brightness: number };
  form?: Record<string, unknown>;
  signals?: Record<string, unknown>;
  proposal?: { tool?: string; arguments?: unknown; calls?: { tool: string; arguments: unknown }[] } | null;
  box?: Box | null;
};

const KINDS = [
  ["sick_note", "Sick note"],
  ["disruption", "Departures board or delay notice"],
  ["defect", "Aircraft defect"],
  ["roster_swap", "Roster swap request"],
  ["certificate", "Certificate"],
] as const;

const TONE = { rejected: "error", reshoot: "pending", confirm: "pending", draft: "ok" } as const;

function Marked({ file, box }: { file: File; box?: Box | null }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      const g = c.getContext("2d");
      if (!g) return;
      g.drawImage(img, 0, 0);
      if (box) {
        const sx = c.width / box.width;
        const sy = c.height / box.height;
        g.lineWidth = Math.max(4, c.width / 250);
        g.strokeStyle = "#ff3b30";
        g.strokeRect(box.x1 * sx, box.y1 * sy, (box.x2 - box.x1) * sx, (box.y2 - box.y1) * sy);
        g.font = `${Math.max(18, c.width / 45)}px system-ui`;
        g.fillStyle = "#ff3b30";
        g.fillText(`damage ${Math.round(box.confidence * 100)}%`, box.x1 * sx, Math.max(24, box.y1 * sy - 10));
      }
    };
    img.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file, box]);
  return <canvas ref={canvas} className="h-auto max-w-full rounded-md border border-line" />;
}

/** A photo of a sick note, a board, a defect or a certificate, checked in fixed steps:
 * picture quality, then a model fills a fixed form, then the rules in code. Nothing changes
 * until a person confirms. */
export function PhotoIntake() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Intake | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const image = f.get("image");
    if (!(image instanceof File) || !image.size) return setError("Choose a photo first.");
    if (!f.get("tail")) f.delete("tail");
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api<Intake>("/api/intake", { method: "POST", form: f }));
      setFile(image);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  }

  const calls = result?.proposal ? (result.proposal.calls ?? [result.proposal as { tool: string; arguments: unknown }]) : [];

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Label label="What it shows">
          <select name="kind" className={control}>
            {KINDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Label>
        <Input label="Aircraft (for a defect)" name="tail" placeholder="VT-SYB" />
        <label className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed border-control bg-sunken px-4 py-6 text-center text-sm text-muted hover:border-accent">
          <ImageUp size={22} className="text-faint" />
          <span>
            <b className="text-foreground">Choose a photo</b> or take one (JPEG, PNG or WebP, under 8 MB)
          </span>
          <input name="image" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="max-w-full text-xs" required />
        </label>
        <p className="text-xs text-faint">Checked in fixed steps: picture quality, then a model reads it into a fixed form, then the rules in code. Defect photos get the damage marked. Nothing changes until a person confirms.</p>
        <div>
          <Button type="submit" disabled={busy}>
            {busy ? <Spinner /> : <Camera size={15} />} Check photo
          </Button>
        </div>
      </form>
      <div className="flex min-w-0 flex-col gap-3">
        {error && <Notice tone="error">{error}</Notice>}
        {busy && (
          <p className="flex items-center gap-2 text-sm text-muted">
            <Spinner /> Reading the photo…
          </p>
        )}
        {result && (
          <>
            <Notice tone={TONE[result.status] ?? "info"}>
              <b className="mr-1 capitalize">{result.status}</b> {result.message}
            </Notice>
            {result.confidence && (
              <p className="text-sm">
                Confidence: <Pill tone={result.confidence === "high" ? "ok" : result.confidence === "low" ? "critical" : "pending"}>{result.confidence}</Pill>
              </p>
            )}
            {file && <Marked file={file} box={result.box} />}
            {result.quality && (
              <p className="text-xs text-muted">
                Picture {result.quality.width}×{result.quality.height}, sharpness {result.quality.sharpness}, brightness {result.quality.brightness}
              </p>
            )}
            {[
              ["What the model read", result.form],
              ["Signals behind the confidence", result.signals],
            ].map(([title, body]) =>
              body && Object.keys(body as object).length ? (
                <details key={String(title)} className="rounded-md border border-line">
                  <summary className="flex items-center gap-2 px-3 py-2 text-sm">
                    <ChevronDown size={14} className="text-faint" /> {String(title)}
                  </summary>
                  <pre className="max-h-72 overflow-auto border-t border-rule bg-sunken p-3 font-mono text-xs">{JSON.stringify(body, null, 2)}</pre>
                </details>
              ) : null,
            )}
            {calls.map((c, i) => (
              <p key={i} className={cx("rounded-md bg-sunken px-3 py-2 text-xs")}>
                Next step: <code className="font-mono font-semibold">{c.tool}</code> <span className="font-mono text-muted">{JSON.stringify(c.arguments)}</span>
              </p>
            ))}
          </>
        )}
        {!result && !busy && !error && (
          <div className="flex flex-1 items-center justify-center rounded-lg border border-line bg-sunken p-8 text-center text-sm text-muted">The reading of the photo shows here.</div>
        )}
      </div>
    </div>
  );
}
