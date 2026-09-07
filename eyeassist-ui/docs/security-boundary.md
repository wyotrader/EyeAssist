EyeAssist gateway production boundary
====================================

Browsers should reach only the port-8080 EyeAssist gateway. In production, bind the internal services to loopback or otherwise private gateway-only access:

- RAG: 8100
- Vision: 8200
- Orchestrator: 8300
- Ollama: 11434

The first native frontend slice does not introduce patient identity, encounter persistence, transcript persistence, image upload, or PDF upload.
