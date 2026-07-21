import { requestJson } from "./requestJson.js";

export function getHealth() {
  return requestJson("GET", "/health");
}

export function getVenues() {
  return requestJson("GET", "/venues");
}

export function getVenue(venueId) {
  return requestJson("GET", `/venues/${venueId}`);
}

export function getSpecs() {
  return requestJson("GET", "/specs");
}

export function getDataSources() {
  return requestJson("GET", "/data/sources");
}

export function simulate(payload) {
  return requestJson("POST", "/simulate", payload);
}

export function simulateTemporal(payload) {
  return requestJson("POST", "/simulate/temporal", payload);
}

export function stressTest(payload) {
  return requestJson("POST", "/stress-test", payload);
}

export function whatIf(payload) {
  return requestJson("POST", "/scenario/what-if", payload);
}

export function compareScenarios(payload) {
  return requestJson("POST", "/scenario/compare", payload);
}

export function chat(payload) {
  return requestJson("POST", "/chat", payload);
}

export function clearConversation(conversationId) {
  return requestJson("DELETE", `/chat/${conversationId}`);
}

export function getRun(runId) {
  return requestJson("GET", `/runs/${runId}`);
}

export function listScenarios() {
  return requestJson("GET", "/scenarios");
}

export function getScenario(slug) {
  return requestJson("GET", `/scenarios/${slug}`);
}
