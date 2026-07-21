import { requestJson } from '../utils/requestJson.js';

export function useVaneAPI() {
  async function chat(message, conversationId = null, scenario = null) {
    return requestJson('POST', '/chat', {
      message,
      conversation_id: conversationId,
      ...(scenario ? { scenario } : {}),
    });
  }

  async function simulate(params) {
    return requestJson('POST', '/simulate', params);
  }

  async function simulateTemporal(params) {
    return requestJson('POST', '/simulate/temporal', params);
  }

  async function stressTest(params) {
    return requestJson('POST', '/stress-test', params);
  }

  async function whatIf(params) {
    return requestJson('POST', '/scenario/what-if', params);
  }

  async function getVenues() {
    return requestJson('GET', '/venues');
  }

  async function getVenue(venueId) {
    return requestJson('GET', `/venues/${venueId}`);
  }

  async function getSpecs() {
    return requestJson('GET', '/specs');
  }

  async function getHealth() {
    return requestJson('GET', '/health');
  }

  async function deleteConversation(conversationId) {
    return requestJson('DELETE', `/chat/${conversationId}`);
  }

  async function getRun(runId) {
    return requestJson('GET', `/runs/${runId}`);
  }

  async function listScenarios() {
    return requestJson('GET', '/scenarios');
  }

  async function getScenario(slug) {
    return requestJson('GET', `/scenarios/${slug}`);
  }

  return {
    chat, simulate, simulateTemporal, stressTest, whatIf,
    getVenues, getVenue, getSpecs, getHealth, deleteConversation,
    getRun, listScenarios, getScenario,
  };
}
