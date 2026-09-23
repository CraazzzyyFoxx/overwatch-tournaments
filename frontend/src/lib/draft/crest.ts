export function teamCrest(team: { id: number; name: string }): { initial: string; hue: number } {
  const match = team.name.match(/[A-Za-z0-9]/);
  const initial = match ? match[0].toUpperCase() : "#";
  // stable hue from id; golden-angle spread keeps adjacent ids visually distinct
  const hue = Math.round((team.id * 137.508) % 360) % 360;
  return { initial, hue };
}
