import { ProviderType } from "../domain/types";
import { ProviderAdapter } from "./base";
import { FlyAdapter } from "./providers/flyAdapter";
import { KongAdapter } from "./providers/kongAdapter";
import { RailwayAdapter } from "./providers/railwayAdapter";
import { RenderAdapter } from "./providers/renderAdapter";
import { SupabaseAdapter } from "./providers/supabaseAdapter";
import { TerraformAdapter } from "./providers/terraformAdapter";

const adapters: Record<ProviderType, ProviderAdapter> = {
  render: new RenderAdapter(),
  railway: new RailwayAdapter(),
  fly: new FlyAdapter(),
  kong: new KongAdapter(),
  terraform: new TerraformAdapter(),
  supabase: new SupabaseAdapter()
};

export function getAdapter(provider: ProviderType): ProviderAdapter {
  return adapters[provider];
}
