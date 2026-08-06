export function debounce(
  fn: (...args: any[]) => any,
  delay: number
): (...args: any[]) => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  return (...args: any[]) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      fn(...args)
      timer = null
    }, delay)
  }
}

export function throttle(
  fn: (...args: any[]) => any,
  interval: number
): (...args: any[]) => void {
  let lastTime = 0
  let timer: ReturnType<typeof setTimeout> | null = null
  return (...args: any[]) => {
    const now = Date.now()
    const remaining = interval - (now - lastTime)
    if (remaining <= 0) {
      if (timer) {
        clearTimeout(timer)
        timer = null
      }
      lastTime = now
      fn(...args)
    } else if (!timer) {
      timer = setTimeout(() => {
        lastTime = Date.now()
        timer = null
        fn(...args)
      }, remaining)
    }
  }
}
