import { z } from "zod";

const envSchema = z.object({
  DATABASE_URL: z.string().url(),
  NEXT_PUBLIC_BETTER_AUTH_URL: z.string().url().default("http://26.41.157.27:3000"),
  NEXT_PUBLIC_API_URL: z.string().default("http://localhost:8000"),
  NODE_ENV: z.enum(["development", "production", "test"]).default("development"),
  APIKEY: z.string().optional(),
  TICKFLOW_KEY: z.string()
});

const parsed = envSchema.safeParse(process.env);

if (!parsed.success) {
  console.error("❌ Invalid environment variables:", parsed.error.flatten().fieldErrors);
  throw new Error("Invalid environment variables");
}

export const env = parsed.data;