"use server";

import prisma from "@/lib/prisma";

export async function checkBanned(email: string): Promise<{ banned: boolean }> {
  const user = await prisma.user.findUnique({ where: { email }, select: { banned: true } });
  return { banned: user?.banned ?? false };
}