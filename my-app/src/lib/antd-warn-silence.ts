/** rc-util 的 warning() 内部用 console.error 输出，console.warn 覆写无效。
 *  利用 rc-util 提供的 preMessage 钩子在消息到达 console.error 前拦截。 */
import { preMessage } from "rc-util/es/warning";

preMessage((msg) => {
  if (msg && msg.includes("antd v5 support React is 16 ~ 18")) return null;
  return msg;
});

// 同样覆写 console.warn 兜底
const _warn = console.warn;
console.warn = (...args: any[]) => {
  if (typeof args[0] === "string" && args[0].includes("antd v5 support React is 16 ~ 18")) return;
  _warn.apply(console, args);
};

// 同样覆写 console.error 兜底
const _error = console.error;
console.error = (...args: any[]) => {
  if (typeof args[0] === "string" && args[0].includes("antd v5 support React is 16 ~ 18")) return;
  _error.apply(console, args);
};

export {};