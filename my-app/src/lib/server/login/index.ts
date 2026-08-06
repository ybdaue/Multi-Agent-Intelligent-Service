import { authClient } from "@/lib/auth-clients"

export async function signin(data: { email: string; password: string }) {
  const { data: result, error } = await authClient.signIn.email({
    email: data.email,
    password: data.password,
  })
  if (error) return { error: error.message || "登录失败" }
  return {
    success: true as const,
    user: result?.user
      ? { id: result.user.id, email: result.user.email, name: result.user.name }
      : null,
  }
}
