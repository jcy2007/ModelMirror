import { type Edge, type Node } from "@xyflow/react";

export type WorkflowNodeKind =
  | "input"
  | "llm"
  | "condition"
  | "code"
  | "variable_assign"
  | "template_transform"
  | "variable_aggregator"
  | "parameter_extractor"
  | "knowledge_retrieval"
  | "document_extractor"
  | "human_intervention"
  | "question_classifier"
  | "agent"
  | "mcp_tool"
  | "time_tool"
  | "http_request"
  | "list_operation"
  | "iteration"
  | "output";

export type ConditionOperator =
  | "equals"
  | "not_equals"
  | "contains"
  | "not_contains"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "empty"
  | "not_empty";

export type CodeOperation = "upper" | "lower" | "replace" | "concat";

export type HttpRequestMethod = "GET" | "POST";

export type ListOperationOperator = "length" | "join" | "first" | "last";

export type VariableType = "string" | "number" | "object" | "array";

/**
 * Common fields shared by every node kind. Kept broad (optional) so read-side
 * cross-kind access like `data.outputVariable` still works, while each kind's
 * discriminated variant adds its required/typed specific fields.
 */
export interface WorkflowNodeDataBase extends Record<string, unknown> {
  kind: WorkflowNodeKind;
  title: string;
  description: string;
  runState?: "running" | "success" | "error";
  // Common optional fields used across many kinds.
  variableType?: VariableType;
  variableName?: string;
  outputVariable?: string;
  modelId?: string;
  prompt?: string;
  errorStrategy?: "fail" | "continue" | "retry";
  retryCount?: string;
}

// ---- Per-kind discriminated variants ----
export interface InputNodeData extends WorkflowNodeDataBase {
  kind: "input";
  variableName: string;
  variableType?: VariableType;
}

export interface LlmNodeData extends WorkflowNodeDataBase {
  kind: "llm";
  modelId: string;
  prompt: string;
  outputVariable: string;
}

export interface ConditionNodeData extends WorkflowNodeDataBase {
  kind: "condition";
  conditionVariable: string;
  conditionOperator: ConditionOperator;
  conditionValue: string;
}

export interface CodeNodeData extends WorkflowNodeDataBase {
  kind: "code";
  codeOperation?: CodeOperation;
  codeInputVariable?: string;
  codeOutputVariable?: string;
  replaceFrom?: string;
  replaceTo?: string;
  concatValue?: string;
}

export interface VariableAssignNodeData extends WorkflowNodeDataBase {
  kind: "variable_assign";
  variableName: string;
  template: string;
}

export interface TemplateTransformNodeData extends WorkflowNodeDataBase {
  kind: "template_transform";
  template: string;
  outputVariable: string;
}

export interface VariableAggregatorNodeData extends WorkflowNodeDataBase {
  kind: "variable_aggregator";
  variableNames: string;
  outputTemplate?: string;
  outputVariable: string;
}

export interface ParameterExtractorNodeData extends WorkflowNodeDataBase {
  kind: "parameter_extractor";
  inputVariable: string;
  schema: string;
  modelId: string;
  outputVariable: string;
}

export interface KnowledgeRetrievalNodeData extends WorkflowNodeDataBase {
  kind: "knowledge_retrieval";
  queryVariable: string;
  top_k?: string;
  outputVariable: string;
}

export interface DocumentExtractorNodeData extends WorkflowNodeDataBase {
  kind: "document_extractor";
  sourcePathVariable: string;
  outputVariable: string;
}

export interface HumanInterventionNodeData extends WorkflowNodeDataBase {
  kind: "human_intervention";
  prompt: string;
  outputVariable: string;
}

export interface QuestionClassifierNodeData extends WorkflowNodeDataBase {
  kind: "question_classifier";
  inputVariable: string;
  categories: string;
  outputVariable: string;
  defaultCategory?: string;
  matchMode?: string;
  caseSensitive?: string;
  useLlmFallback?: string;
  modelId?: string;
  llmFallbackPrompt?: string;
}

export interface AgentNodeData extends WorkflowNodeDataBase {
  kind: "agent";
  agentMode?: string;
  instruction: string;
  modelId: string;
  toolNames?: string;
  outputVariable: string;
  maxIterations?: string;
  temperature?: string;
  promptSuffix?: string;
}

export interface McpToolNodeData extends WorkflowNodeDataBase {
  kind: "mcp_tool";
  toolName: string;
  argumentsJson: string;
  outputVariable: string;
  errorMode?: string;
}

export interface TimeToolNodeData extends WorkflowNodeDataBase {
  kind: "time_tool";
  operation?: string;
  formatString?: string;
  outputVariable: string;
}

export interface HttpRequestNodeData extends WorkflowNodeDataBase {
  kind: "http_request";
  url: string;
  method?: HttpRequestMethod;
  headersJson?: string;
  bodyVariable?: string;
  outputVariable: string;
}

export interface ListOperationNodeData extends WorkflowNodeDataBase {
  kind: "list_operation";
  inputVariable: string;
  operator: ListOperationOperator;
  joinSeparator?: string;
  outputVariable: string;
}

export interface IterationNodeData extends WorkflowNodeDataBase {
  kind: "iteration";
  inputVariable: string;
  iterationVariable: string;
  itemTemplate: string;
  outputVariable: string;
}

export interface OutputNodeData extends WorkflowNodeDataBase {
  kind: "output";
  outputVariable: string;
}

/** Discriminated union of all node kinds' data. */
export type WorkflowNodeData =
  | InputNodeData
  | LlmNodeData
  | ConditionNodeData
  | CodeNodeData
  | VariableAssignNodeData
  | TemplateTransformNodeData
  | VariableAggregatorNodeData
  | ParameterExtractorNodeData
  | KnowledgeRetrievalNodeData
  | DocumentExtractorNodeData
  | HumanInterventionNodeData
  | QuestionClassifierNodeData
  | AgentNodeData
  | McpToolNodeData
  | TimeToolNodeData
  | HttpRequestNodeData
  | ListOperationNodeData
  | IterationNodeData
  | OutputNodeData;

export type WorkflowNode = Node<WorkflowNodeData, "workflowNode">;

export type WorkflowEdge = Edge;

export interface WorkflowDefinition {
  id: string;
  title: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  updatedAt: string;
}

export interface WorkflowRunEvent {
  event:
    | "workflow_meta"
    | "node_start"
    | "node_delta"
    | "human_intervention_pending"
    | "heartbeat"
    | "node_end"
    | "workflow_end"
    | "error";
  task_id?: string;
  node_id?: string;
  node_title?: string;
  node_type?: WorkflowNodeKind;
  prompt?: string;
  output?: string;
  output_variable?: string;
  variable?: string;
  final_output?: string;
  variables?: Record<string, string>;
  message?: string;
  at?: number;
}
