export class RequestError extends Error {
  status?: number
  timeout?: boolean

  constructor(message: string, options?: { status?: number; timeout?: boolean }) {
    super(message)
    this.name = "RequestError"
    this.status = options?.status
    this.timeout = options?.timeout
  }
}

interface CustomRequestInit extends RequestInit {
  timeout?: number
}

function combineSignals(...signals: AbortSignal[]): AbortSignal {
  const controller = new AbortController()
  for (const signal of signals) {
    if (signal.aborted) {
      controller.abort(signal.reason)
      return controller.signal
    }
    signal.addEventListener("abort", () => controller.abort(signal.reason), { once: true })
  }
  return controller.signal
}

export async function request(url: string, options: CustomRequestInit = {}): Promise<Response> {
  const { timeout = 10000, ...fetchOptions } = options

  let timeoutAbort: AbortController | null = null
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  let timedOut = false

  if (timeout > 0) {
    timeoutAbort = new AbortController()
    timeoutId = setTimeout(() => {
      timedOut = true
      timeoutAbort!.abort()
    }, timeout)
  }

  if (timeoutAbort && fetchOptions.signal) {
    fetchOptions.signal = combineSignals(fetchOptions.signal as AbortSignal, timeoutAbort.signal)
  } else if (timeoutAbort) {
    fetchOptions.signal = timeoutAbort.signal
  }

  try {
    return await fetch(url, fetchOptions)
  } catch (err) {
    if (timedOut) {
      throw new RequestError("请求超时", { timeout: true })
    }
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err
    }
    if (err instanceof TypeError) {
      throw new RequestError("网络错误，请检查连接")
    }
    throw err
  } finally {
    clearTimeout(timeoutId)
  }
}

export async function requestJSON<T>(url: string, options: CustomRequestInit = {}): Promise<T> {
  const res = await request(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers as Record<string, string>) },
  })
  if (!res.ok) {
    throw new RequestError(`请求失败 (${res.status})`, { status: res.status })
  }
  return res.json()
}
