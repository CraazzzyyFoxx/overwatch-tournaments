export interface DiscordRole {
  id: string;
  name: string;
  color: string | null;
  position: number;
  managed: boolean;
}

export interface DiscordChannel {
  id: string;
  name: string;
  category_name: string | null;
  position: number;
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
