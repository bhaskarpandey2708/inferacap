"""CLI Entrypoint to launch the InferaCap Live Online Inference Gateway."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from gateway.config import GatewayConfig
from gateway.router import LiveEconomicRouter
from gateway.server import LiveGatewayServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("inferacap.cli")


def main():
    parser = argparse.ArgumentParser(
        description="InferaCap Live Online Inference Load Balancer & Gateway"
    )
    parser.add_argument(
        "config",
        nargs="?",
        default="gateway/sample_gateway_config.json",
        help="Path to gateway configuration JSON file (default: gateway/sample_gateway_config.json)",
    )
    parser.add_argument("--host", help="Override listen host (e.g. 0.0.0.0 or 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Override listen port (e.g. 8080)")

    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)

    logger.info(f"Loading InferaCap Gateway configuration from {config_path}")
    config = GatewayConfig.from_file(config_path)

    if args.host:
        config.listen_host = args.host
    if args.port:
        config.listen_port = args.port

    router = LiveEconomicRouter(config)
    server = LiveGatewayServer(config, router)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        await server.start()
        logger.info(f"Gateway ID: {config.gateway_id}")
        logger.info(f"Active Regions: {list(config.regions.keys())}")
        logger.info(f"Allowed Cross-Region Routes: {len(config.allowed_routes)}")
        logger.info("Serving OpenAI-compatible endpoints:")
        logger.info(f"  POST http://{config.listen_host}:{config.listen_port}/v1/chat/completions")
        logger.info(f"  POST http://{config.listen_host}:{config.listen_port}/v1/completions")
        logger.info(f"  GET  http://{config.listen_host}:{config.listen_port}/v1/models")
        logger.info(f"  GET  http://{config.listen_host}:{config.listen_port}/v1/metrics")
        logger.info(f"  GET  http://{config.listen_host}:{config.listen_port}/health")

        stop_event = asyncio.Event()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass  # Windows or non-main thread

        try:
            await stop_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            logger.info("Initiating graceful shutdown...")
            await server.stop()

    try:
        loop.run_until_complete(run())
    finally:
        loop.close()
        logger.info("Gateway terminated cleanly.")


if __name__ == "__main__":
    main()
