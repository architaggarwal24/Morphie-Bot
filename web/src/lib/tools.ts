import { Calculator, Clock, FileSearch, Globe, Wrench, type LucideIcon } from "lucide-react";

export interface ToolMeta {
  icon: LucideIcon;
  name: string;
  active: string;
  done: string;
  hue: string; // a CSS color for the tool's accent
}

export const TOOLS: Record<string, ToolMeta> = {
  calculator: { icon: Calculator, name: "Calculator", active: "Using the calculator", done: "Used the calculator", hue: "var(--warning)" },
  get_current_time: { icon: Clock, name: "Clock", active: "Checking the time", done: "Checked the time", hue: "var(--cyan)" },
  web_search: { icon: Globe, name: "Web", active: "Searching the web", done: "Searched the web", hue: "var(--indigo)" },
  search_documents: { icon: FileSearch, name: "Docs", active: "Searching your documents", done: "Searched your documents", hue: "var(--pink)" },
};

export function toolMeta(tool: string): ToolMeta {
  return TOOLS[tool] ?? { icon: Wrench, name: tool, active: `Using ${tool}`, done: `Used ${tool}`, hue: "var(--primary)" };
}

export interface Suggestion {
  tool: keyof typeof TOOLS;
  title: string;
  prompt: string;
}

export const SUGGESTIONS: Suggestion[] = [
  { tool: "calculator", title: "Crunch numbers", prompt: "What's 20% of 500?" },
  { tool: "search_documents", title: "Ask your documents", prompt: "What does my resume say about Python?" },
  { tool: "get_current_time", title: "Check any clock", prompt: "What time is it in Tokyo?" },
  { tool: "web_search", title: "Search the web", prompt: "Search the web for today's top tech news." },
];
