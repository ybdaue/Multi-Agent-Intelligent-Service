import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

//安全地合并 Tailwind CSS 类名，解决类名冲突、覆盖和动态样式的问题
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
