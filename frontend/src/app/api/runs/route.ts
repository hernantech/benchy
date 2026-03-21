import { NextResponse } from "next/server";
import { MOCK_RUNS, MOCK_STEPS, MOCK_MEASUREMENTS, MOCK_DIAGNOSIS } from "@/lib/mock-data";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const runId = url.searchParams.get("id");
  const action = url.searchParams.get("action");

  if (action === "instruments") {
    return NextResponse.json({ instruments: [] });
  }

  if (runId) {
    const run = MOCK_RUNS.find((r) => r.id === runId);
    if (!run) return NextResponse.json({ error: "Run not found" }, { status: 404 });

    return NextResponse.json({
      run,
      steps: MOCK_STEPS.filter((s) => s.run_id === runId),
      measurements: MOCK_MEASUREMENTS.filter((m) => m.run_id === runId),
      diagnosis: runId === MOCK_DIAGNOSIS.run_id ? MOCK_DIAGNOSIS : null,
    });
  }

  return NextResponse.json({ runs: MOCK_RUNS });
}

export async function POST(req: Request) {
  const body = await req.json();

  const run = {
    id: `run-${Date.now()}`,
    status: "queued" as const,
    goal: body.goal || "Unnamed run",
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    device_id: "bench-01",
    trigger_type: body.trigger_type || "manual",
    trigger_ref: body.trigger_ref || null,
  };

  return NextResponse.json({ run }, { status: 201 });
}
