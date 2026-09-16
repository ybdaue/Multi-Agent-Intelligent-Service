import type { Metadata } from "next";
import LegalPage from "@/components/legal-page";

export const metadata: Metadata = {
  title: "用户协议 | AI 智能平台",
};

export default function TermsPage() {
  return (
    <LegalPage title="用户协议" updatedAt="2026-08-13">
      <p>【占位内容，正式上线前请由法务审核补充。】</p>
      <h2>1. 服务说明</h2>
      <p>本站提供基于 AI 的智能对话、数据分析、内容生成与财务辅助等服务，具体以平台实际开放的功能为准。</p>
      <h2>2. 账号与使用规范</h2>
      <p>请填写具体条款。</p>
      <h2>3. 知识产权</h2>
      <p>请填写具体条款。</p>
      <h2>4. 免责声明</h2>
      <p>请填写具体条款。</p>
      <h2>5. 协议变更</h2>
      <p>请填写具体条款。</p>
    </LegalPage>
  );
}
