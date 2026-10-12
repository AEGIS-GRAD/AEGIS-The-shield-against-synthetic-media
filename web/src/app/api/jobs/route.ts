import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { analyses as mockAnalyses, reportJson as mockReport } from "@/lib/mock";

const JOBS_DIR = path.join(process.cwd(), ".jobs");
const JOBS_FILE = path.join(JOBS_DIR, "jobs.json");

function ensureJobsFile() {
  if (!fs.existsSync(JOBS_DIR)) {
    fs.mkdirSync(JOBS_DIR, { recursive: true });
  }
  if (!fs.existsSync(JOBS_FILE)) {
    fs.writeFileSync(JOBS_FILE, JSON.stringify([], null, 2), "utf-8");
  }
}

function readJobs() {
  try {
    ensureJobsFile();
    const data = fs.readFileSync(JOBS_FILE, "utf-8");
    return JSON.parse(data);
  } catch (err) {
    console.error("Error reading jobs:", err);
    return [];
  }
}

function writeJobs(jobs: any[]) {
  try {
    ensureJobsFile();
    fs.writeFileSync(JOBS_FILE, JSON.stringify(jobs, null, 2), "utf-8");
  } catch (err) {
    console.error("Error writing jobs:", err);
  }
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const id = searchParams.get("id");
  const realJobs = readJobs();

  if (id) {
    // Check real jobs first
    const found = realJobs.find((j: any) => j.id === id || j.job_id === id);
    if (found) {
      return NextResponse.json(found);
    }
    // Fallback to mock demo report if AEG-1042 or matching demo ID
    if (id === "AEG-1042" || mockAnalyses.some((a) => a.id === id)) {
      return NextResponse.json({
        ...mockReport,
        job_id: id,
        is_demo: true,
      });
    }
    return NextResponse.json({ error: "Job not found" }, { status: 404 });
  }

  // Return real jobs merged with mock demo analyses labeled with is_demo: true
  const labeledDemos = mockAnalyses.map((a) => ({
    ...a,
    is_demo: true,
  }));

  const all = [...realJobs, ...labeledDemos];
  return NextResponse.json(all);
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const realJobs = readJobs();

    const newJob = {
      id: body.id || `AEG-${Date.now().toString().slice(-4)}`,
      file: body.file || "uploaded_media.mp4",
      modality: body.modality || "video",
      verdict: body.verdict || "synthetic",
      confidence: body.confidence || 0.85,
      time: new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }),
      status: "Complete",
      is_demo: false,
      timestamp: new Date().toISOString(),
      raw_result: body,
    };

    realJobs.unshift(newJob);
    writeJobs(realJobs);

    return NextResponse.json(newJob, { status: 201 });
  } catch (err: any) {
    return NextResponse.json({ error: err.message || "Invalid payload" }, { status: 400 });
  }
}
