import type { Metadata } from "next";
import LegalPage from "@/components/legal-page";

export const metadata: Metadata = {
  title: "隐私政策 | AI 智能平台",
};

export default function PrivacyPage() {
  return (
    <LegalPage title="隐私政策" updatedAt="2026-08-13">
      <p>【占位内容，正式上线前请由法务审核补充。】</p>
      <h2>1. 我们收集的信息</h2>
      <p>请填写具体条款。</p>
      <h2>2. 信息的使用</h2>
      <p>请填写具体条款。</p>
      <h2>3. 信息的共享与披露</h2>
      <p>请填写具体条款。</p>
      <h2>4. 信息存储与安全</h2>
      <p>请填写具体条款。</p>
      <h2>5. 您的权利</h2>
      <p>请填写具体条款。</p>
      <h2>6. 联系我们</h2>
      <p>请填写具体条款。</p>
    </LegalPage>
  );
}
