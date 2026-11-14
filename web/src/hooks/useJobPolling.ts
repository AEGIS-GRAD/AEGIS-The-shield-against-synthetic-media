"use client";

import { useEffect, useState } from "react";

export type JobPollingStatus =
  | "idle"
  | "polling"
  | "complete"
  | "failed"
  | "not_found"
  | "timeout"
  | "error";

export interface UseJobPollingOptions {
  intervalMs?: number;
  maxAttempts?: number;
  maxBackoffMs?: number;
}

export interface UseJobPollingResult<T = any> {
  status: JobPollingStatus;
  job: T | null;
  error: string | null;
  attempts: number;
}

export function useJobPolling<T = any>(
  jobId: string | null | undefined,
  options: UseJobPollingOptions = {}
): UseJobPollingResult<T> {
  const { intervalMs = 1000, maxAttempts = 20, maxBackoffMs = 8000 } = options;

  const [status, setStatus] = useState<JobPollingStatus>(jobId ? "polling" : "idle");
  const [job, setJob] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempts, setAttempts] = useState(0);

  useEffect(() => {
    if (!jobId) {
      setStatus("idle");
      setJob(null);
      setError(null);
      setAttempts(0);
      return;
    }

    let cancelled = false;
    let timerId: ReturnType<typeof setTimeout> | null = null;
    let activeController: AbortController | null = null;
    let attemptCount = 0;
    let consecutiveFailures = 0;

    setStatus("polling");
    setError(null);
    setAttempts(0);

    const scheduleNext = (delayMs: number) => {
      if (cancelled) return;
      timerId = setTimeout(() => {
        void pollOnce();
      }, delayMs);
    };

    const pollOnce = async () => {
      if (cancelled) return;

      if (attemptCount >= maxAttempts) {
        setStatus("timeout");
        setError(`Polling timed out after ${maxAttempts} attempts for job ${jobId}`);
        return;
      }

      attemptCount += 1;
      setAttempts(attemptCount);

      activeController = new AbortController();
      try {
        const res = await fetch(`/api/jobs?id=${encodeURIComponent(jobId)}`, {
          signal: activeController.signal,
        });

        if (cancelled) return;

        if (res.status === 404) {
          setStatus("not_found");
          setError(`Job ${jobId} was not found`);
          return;
        }

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        if (cancelled) return;

        consecutiveFailures = 0;
        setJob(data as T);

        const jobStatus = String(data?.status || "").toLowerCase();
        if (jobStatus === "complete" || jobStatus === "completed") {
          setStatus("complete");
          return;
        }
        if (jobStatus === "failed" || jobStatus === "error") {
          setStatus("failed");
          setError(data?.error || "Analysis job failed");
          return;
        }

        if (attemptCount >= maxAttempts) {
          setStatus("timeout");
          setError(`Polling timed out after ${maxAttempts} attempts for job ${jobId}`);
          return;
        }

        scheduleNext(intervalMs);
      } catch (err: any) {
        if (cancelled || err?.name === "AbortError") return;

        consecutiveFailures += 1;
        setError(err?.message || "Failed to poll job status");

        if (attemptCount >= maxAttempts) {
          setStatus("error");
          return;
        }

        const backoff = Math.min(maxBackoffMs, intervalMs * Math.pow(2, consecutiveFailures));
        scheduleNext(backoff);
      }
    };

    void pollOnce();

    return () => {
      cancelled = true;
      if (timerId !== null) clearTimeout(timerId);
      if (activeController) activeController.abort();
    };
  }, [jobId, intervalMs, maxAttempts, maxBackoffMs]);

  return { status, job, error, attempts };
}

