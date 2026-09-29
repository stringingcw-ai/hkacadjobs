// Test helpers: a scripted fake Claude client, in-memory usage store, and the fixture data.
// Only the *_test.ts files import this, so it is never deployed.

import type Anthropic from "@anthropic-ai/sdk";
import type { ClaudeClient } from "./claude.ts";
import { type Config, loadConfig } from "./config.ts";
import { type JobSet, JobsSource } from "./jobs.ts";
import type { Profile } from "./types.ts";
import type { QuotaStatus, UsageRow, UsageStore } from "./usage.ts";

type CreateParams = Anthropic.Beta.Messages.MessageCreateParamsNonStreaming;
type Message = Anthropic.Beta.Messages.BetaMessage;

export const TODAY = "2026-09-29";
export const SERVICE_KEY = "service-role-key-for-tests";

export interface Persona {
  name: string;
  cv: string;
  profile: Profile;
  relevant: string[];
}

export async function personas(): Promise<Persona[]> {
  return JSON.parse(await Deno.readTextFile(new URL("./testdata/personas.json", import.meta.url)));
}

export async function fixtureCsv(): Promise<string> {
  return await Deno.readTextFile(new URL("./testdata/jobs_fixture.csv", import.meta.url));
}

/** The fixture as the function sees it on TODAY (Hong Kong time). */
export async function fixtureJobs(): Promise<JobSet> {
  const csv = await fixtureCsv();
  const source = new JobsSource({
    url: "https://example.test/jobs.csv",
    fetch: () => Promise.resolve(new Response(csv)),
    now: () => new Date(`${TODAY}T04:00:00Z`),
  });
  return await source.get();
}

export function testConfig(env: Record<string, string> = {}): Config {
  const values: Record<string, string> = {
    ANTHROPIC_API_KEY: "test-key",
    SUPABASE_URL: "https://project.supabase.co",
    SUPABASE_ANON_KEY: "anon-key",
    SUPABASE_SERVICE_ROLE_KEY: SERVICE_KEY,
    ...env,
  };
  return loadConfig((name) => values[name]);
}

/** A Claude reply. `json` becomes the text of a structured-output reply. */
export function reply(opts: {
  text?: string;
  json?: unknown;
  stop?: string;
  content?: unknown[];
  input?: number;
  output?: number;
}): Message {
  return {
    id: "msg_test",
    type: "message",
    role: "assistant",
    model: "claude-sonnet-5-5",
    content: opts.content ?? [{ type: "text", text: opts.text ?? JSON.stringify(opts.json ?? {}) }],
    stop_reason: opts.stop ?? "end_turn",
    stop_sequence: null,
    usage: {
      input_tokens: opts.input ?? 1_000,
      output_tokens: opts.output ?? 200,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
    },
  } as unknown as Message;
}

type Scripted = Message | Error | ((params: CreateParams) => Message);

/** Answers each call with the next scripted reply (or throws it), and records what was sent. */
export class FakeClaude implements ClaudeClient {
  readonly calls: CreateParams[] = [];
  readonly options: unknown[] = [];

  constructor(private readonly script: Scripted[]) {}

  beta = {
    messages: {
      create: (params: CreateParams, options?: unknown): Promise<Message> => {
        this.calls.push(structuredClone(params));
        this.options.push(options);
        const next = this.script.shift();
        if (!next) return Promise.reject(new Error("FakeClaude: no reply scripted for this call"));
        if (next instanceof Error) return Promise.reject(next);
        return Promise.resolve(typeof next === "function" ? next(params) : next);
      },
    },
  };

  /** The text of the user message in call `i` */
  userText(i: number): string {
    const content = this.calls[i].messages[0].content;
    return typeof content === "string" ? content : JSON.stringify(content);
  }
}

/** An error shaped like the SDK's APIError */
export function apiError(status: number | undefined, name = "APIError"): Error {
  const err = new Error(`fake ${status ?? name}`) as Error & { status?: number };
  err.name = name;
  err.status = status;
  return err;
}

export class MemoryUsage implements UsageStore {
  readonly rows: UsageRow[] = [];
  today: Partial<QuotaStatus> = {};
  down = false;

  status(_userId: string | null): Promise<QuotaStatus> {
    if (this.down) return Promise.reject(new Error("database unavailable"));
    return Promise.resolve({ userProfiles: 0, userMatches: 0, siteCostUsd: 0, alertCostUsd: 0, ...this.today });
  }

  record(row: UsageRow): Promise<void> {
    this.rows.push(row);
    return Promise.resolve();
  }
}
