import { redirect } from "next/navigation";
import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import prisma from "@/lib/prisma";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import AdminLayoutDynamic from "./_AdminLayoutDynamic";

export const dynamic = "force-dynamic";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) redirect("/login");

  const user = await prisma.user.findUnique({ where: { id: session.user.id }, select: { banned: true } });
  if (user?.banned) redirect("/login");

  const role = (session.user as { role?: string }).role ?? "user";
  if (role !== "admin" && role !== "superAdmin") {
    redirect("/home");
  }

  return (
    <AntdRegistry>
      <AdminLayoutDynamic role={role}>
        {children}
      </AdminLayoutDynamic>
    </AntdRegistry>
  );
}