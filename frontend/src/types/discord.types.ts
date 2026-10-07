export interface DiscordRole {
  id: string;
  name: string;
  color: string | null;
  position: number;
  managed: boolean;
}

/** What the bot needs on a voice channel (or its category) to move members through it. */
export type DiscordVoicePermission = "view_channel" | "connect" | "move_members";

export interface DiscordChannel {
  id: string;
  name: string;
  type: "text" | "voice" | "category";
  category_id: string | null;
  category_name: string | null;
  position: number;
  /** Voices and categories: what the bot lacks. `null` = unknown, or a text channel. */
  missing_permissions: DiscordVoicePermission[] | null;
}

export interface DiscordGuildInfo {
  guild_id: string | null;
  connected: boolean;
  name?: string | null;
  icon_url?: string | null;
  member_count?: number;
  owner_id?: string | null;
  owner_name?: string | null;
  owner_avatar_url?: string | null;
  error?: string;
}

export interface DiscordRolesResponse {
  guild_id: string | null;
  roles: DiscordRole[];
  error?: string;
}

export interface DiscordChannelsResponse {
  guild_id: string | null;
  channels: DiscordChannel[];
  error?: string;
}
