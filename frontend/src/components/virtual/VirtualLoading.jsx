import React from "react";

export default function VirtualLoading({ rows = 5 }) {
  return (
    <div
      className="virtualLoadingSkeleton"
      aria-label="Loading matches"
    >
      {Array.from({ length: rows }).map(
        (_, index) => (
          <div
            key={index}
            style={{
              padding: "14px 10px",
              marginBottom: "8px",
              borderRadius: "10px",
              background:
                "rgba(148,163,184,0.08)",
              border:
                "1px solid rgba(148,163,184,0.08)",
            }}
          >
            <div
              style={{
                width: "55%",
                height: "10px",
                marginBottom: "9px",
                borderRadius: "6px",
                background:
                  "rgba(148,163,184,0.16)",
                animation:
                  "virtualSkeletonPulse 1.2s ease-in-out infinite",
              }}
            />

            <div
              style={{
                width: "42%",
                height: "10px",
                marginBottom: "12px",
                borderRadius: "6px",
                background:
                  "rgba(148,163,184,0.12)",
                animation:
                  "virtualSkeletonPulse 1.2s ease-in-out infinite",
              }}
            />

            <div
              style={{
                display: "flex",
                gap: "6px",
              }}
            >
              {[1, 2, 3].map(
                (item) => (
                  <div
                    key={item}
                    style={{
                      flex: 1,
                      height: "34px",
                      borderRadius: "7px",
                      background:
                        "rgba(148,163,184,0.10)",
                      animation:
                        "virtualSkeletonPulse 1.2s ease-in-out infinite",
                    }}
                  />
                )
              )}
            </div>
          </div>
        )
      )}

      <style>
        {`
          @keyframes virtualSkeletonPulse {
            0% {
              opacity: 0.4;
            }

            50% {
              opacity: 0.9;
            }

            100% {
              opacity: 0.4;
            }
          }
        `}
      </style>
    </div>
  );
}
