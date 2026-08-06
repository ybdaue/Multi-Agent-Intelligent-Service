import { createDeepSeek } from "@ai-sdk/deepseek";
import { streamText, convertToModelMessages } from "ai";
import { z } from "zod";

const RequestSchema = z.object({
  messages: z.array(z.any()).min(1),
});

const deepseek = createDeepSeek({
  apiKey: process.env.APIKEY,
});

export async function POST(req: Request) {
  const body = await req.json();
  const parsed = RequestSchema.safeParse(body);

  if (!parsed.success) {
    return new Response(JSON.stringify({ error: "Invalid request body" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const { messages: uiMessages } = parsed.data;
  const modelMessages = await convertToModelMessages(uiMessages);

  const result = streamText({
    model: deepseek("deepseek-chat"),
    messages: modelMessages,
    system: "你是一个智能助手",
  });

  return result.toUIMessageStreamResponse({ originalMessages: uiMessages });
}
