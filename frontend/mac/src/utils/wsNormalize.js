/**
 * Server often emits camelCase (agentId, itemId); UI + mock use snake_case.
 * Normalize once per WS message so SwarmGrid / items / legacy agents work.
 */
export function normalizeWsEventData(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return data;
  const o = { ...data };
  if (o.agentId != null && o.agent_id == null) o.agent_id = o.agentId;
  if (o.itemId != null && o.item_id == null) o.item_id = o.itemId;
  if (o.name != null && o.name_guess == null) o.name_guess = o.name;
  if (o.pipelineStage != null && o.pipeline_stage == null) o.pipeline_stage = o.pipelineStage;
  if (o.stage != null && o.pipeline_stage == null) o.pipeline_stage = o.stage;
  if (o.agent == null && o.agentId != null) o.agent = o.agentId;
  if (o.message == null && o.error != null) o.message = o.error;
  return o;
}
