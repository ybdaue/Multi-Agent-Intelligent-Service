import { NextResponse } from "next/server";
import type { ServiceItem } from "@/types/service";

const services: ServiceItem[] = [
  { id: "content", title: "AI 内容生成", description: "智能写作、文案创作、文章生成", icon: "✍️" },
  { id: "legal", title: "AI 法律服务", description: "法律咨询、合同审核、法规检索", icon: "⚖️" },
  { id: "finance", title: "AI 金融服务", description: "财务分析、投资建议、风险评估", icon: "💰" },
  { id: "data", title: "AI 数据分析", description: "数据可视化、趋势预测、报表生成", icon: "📊", comingSoon: true },
  { id: "code", title: "AI 代码助手", description: "代码生成、调试优化、技术问答", icon: "💻", comingSoon: true },
  { id: "image", title: "AI 图像创作", description: "文生图、图生图、风格迁移", icon: "🎨", comingSoon: true },
];

export async function GET() {
  return NextResponse.json({ services });
}
