"use client";

const GlassGlow = () => {
  return (
    <div className="pointer-events-none absolute inset-0">
      <div
        className="absolute -top-24 -left-20 h-72 w-72 rounded-full blur-3xl"
        style={{ backgroundColor: "rgb(var(--lg-a) / 0.14)" }}
      />
      <div
        className="absolute -top-28 right-0 h-80 w-80 rounded-full blur-3xl"
        style={{ backgroundColor: "rgb(var(--lg-b) / 0.12)" }}
      />
      <div
        className="absolute -bottom-24 left-1/3 h-80 w-80 rounded-full blur-3xl"
        style={{ backgroundColor: "rgb(var(--lg-c) / 0.10)" }}
      />
      <div className="absolute inset-0 bg-linear-to-b from-transparent via-transparent to-background/25" />
    </div>
  );
};

export default GlassGlow;
