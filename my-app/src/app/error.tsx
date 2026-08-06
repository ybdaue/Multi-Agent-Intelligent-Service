"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        gap: "1rem",
        color: "#6b7280",
      }}
    >
      <p>页面遇到了意外错误</p>
      <button
        onClick={() => reset()}
        style={{
          padding: "0.5rem 1.5rem",
          background: "#6366f1",
          color: "#fff",
          border: "none",
          borderRadius: "0.5rem",
          cursor: "pointer",
        }}
      >
        重新加载
      </button>
    </div>
  );
}
