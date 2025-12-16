#!/usr/bin/env python3
"""
EvaRAG Crawler v3.2 - Monitoring Temps Réel
==========================================

Script de monitoring avancé pour surveiller les performances et la santé
du service crawler pendant le déploiement et en production.

Features:
✅ Surveillance temps réel des métriques
✅ Détection automatique des anomalies  
✅ Alertes visuelles et sonores
✅ Comparaison performance v3.1 vs v3.2
✅ Export des données de monitoring
✅ Interface CLI interactive

Usage:
    python3 monitor_v32.py                    # Monitoring standard
    python3 monitor_v32.py --live             # Mode temps réel
    python3 monitor_v32.py --compare          # Comparaison avant/après
    python3 monitor_v32.py --export report    # Export rapport
    python3 monitor_v32.py --alerts           # Mode alertes
"""

import asyncio
import json
import time
import sys
import os
import argparse
import signal
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    import httpx
    import psutil
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.layout import Layout
    from rich.align import Align
    from rich.text import Text
except ImportError as e:
    print("❌ Missing dependencies. Install with:")
    print("pip install httpx psutil rich")
    sys.exit(1)

# ==============================================
# CONFIGURATION
# ==============================================

@dataclass
class MonitorConfig:
    base_url: str = "http://localhost:11235"
    refresh_interval: float = 5.0
    alert_thresholds: Dict[str, float] = None
    export_dir: str = "monitoring_data"
    max_history: int = 1000
    
    def __post_init__(self):
        if self.alert_thresholds is None:
            self.alert_thresholds = {
                "memory_mb": 1000.0,
                "cpu_percent": 80.0,
                "response_time": 120.0,
                "error_rate": 0.1,
                "pages_per_minute": 5.0  # Minimum attendu
            }

@dataclass 
class HealthMetrics:
    timestamp: float
    status: str
    memory_mb: float
    cpu_percent: float
    uptime_seconds: float
    active_jobs: int = 0
    response_time: float = 0.0
    version: str = "unknown"
    v2_enabled: bool = False
    
    # Métriques calculées
    pages_crawled: int = 0
    success_rate: float = 0.0
    error_count: int = 0

@dataclass
class CrawlMetrics:
    timestamp: float
    total_requests: int = 0
    successful_crawls: int = 0
    failed_crawls: int = 0
    total_pages: int = 0
    avg_pages_per_crawl: float = 0.0
    avg_duration: float = 0.0
    improvements_used: int = 0

# ==============================================
# MONITORING CORE
# ==============================================

class EvaRAGMonitor:
    def __init__(self, config: MonitorConfig):
        self.config = config
        self.console = Console()
        self.client = httpx.AsyncClient(timeout=30.0)
        self.running = True
        self.metrics_history: List[HealthMetrics] = []
        self.crawl_history: List[CrawlMetrics] = []
        self.alerts_triggered: List[Dict] = []
        
        # Création répertoire export
        Path(self.config.export_dir).mkdir(exist_ok=True)
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        
    def stop_monitoring(self):
        """Arrêt propre du monitoring"""
        self.running = False
        self.console.print("🛑 Stopping monitoring...")
        
    async def fetch_health_metrics(self) -> Optional[HealthMetrics]:
        """Récupère les métriques de santé du service"""
        try:
            start_time = time.time()
            
            # Health basique
            health_resp = await self.client.get(f"{self.config.base_url}/health")
            response_time = time.time() - start_time
            
            if health_resp.status_code != 200:
                return None
                
            health_data = health_resp.json()
            
            # Health détaillé (si disponible)
            detailed_data = {}
            try:
                detailed_resp = await self.client.get(f"{self.config.base_url}/health/detailed")
                if detailed_resp.status_code == 200:
                    detailed_data = detailed_resp.json()
            except:
                pass
                
            # Configuration (si disponible)
            config_data = {}
            try:
                config_resp = await self.client.get(f"{self.config.base_url}/debug/config")
                if config_resp.status_code == 200:
                    config_data = config_resp.json()
            except:
                pass
            
            # Construction des métriques
            metrics = HealthMetrics(
                timestamp=time.time(),
                status=health_data.get("status", "unknown"),
                memory_mb=health_data.get("memory_mb", 0.0),
                cpu_percent=health_data.get("cpu_percent", 0.0),
                uptime_seconds=health_data.get("uptime_seconds", 0.0),
                response_time=response_time,
                active_jobs=detailed_data.get("active_jobs", 0),
                version=detailed_data.get("version", config_data.get("version", "unknown")),
                v2_enabled=config_data.get("feature_flags", {}).get("v2_improvements", False)
            )
            
            # Statistiques de crawling si disponibles
            crawl_stats = detailed_data.get("crawl_stats", {}).get("daily", {})
            if crawl_stats:
                metrics.pages_crawled = crawl_stats.get("total_pages_processed", 0)
                total_requests = crawl_stats.get("total_requests", 1)
                successful = crawl_stats.get("successful_crawls", 0)
                metrics.success_rate = successful / total_requests if total_requests > 0 else 0.0
                metrics.error_count = crawl_stats.get("failed_crawls", 0)
            
            return metrics
            
        except Exception as e:
            self.console.print(f"❌ Error fetching metrics: {e}")
            return None
    
    async def fetch_crawl_metrics(self) -> Optional[CrawlMetrics]:
        """Récupère les métriques de crawling détaillées"""
        try:
            resp = await self.client.get(f"{self.config.base_url}/metrics")
            if resp.status_code != 200:
                return None
                
            data = resp.json()
            daily_stats = data.get("daily", {})
            v2_stats = data.get("v2_improvements", {})
            
            return CrawlMetrics(
                timestamp=time.time(),
                total_requests=daily_stats.get("total_requests", 0),
                successful_crawls=daily_stats.get("successful_crawls", 0),
                failed_crawls=daily_stats.get("failed_crawls", 0),
                total_pages=daily_stats.get("total_pages_processed", 0),
                avg_duration=daily_stats.get("average_processing_time", 0.0),
                improvements_used=v2_stats.get("bfs_corrections", 0)
            )
            
        except Exception as e:
            return None
    
    def check_alerts(self, metrics: HealthMetrics) -> List[Dict]:
        """Vérifie les seuils d'alerte et génère les alertes"""
        alerts = []
        thresholds = self.config.alert_thresholds
        
        # Alerte mémoire
        if metrics.memory_mb > thresholds["memory_mb"]:
            alerts.append({
                "type": "memory",
                "level": "warning",
                "message": f"High memory usage: {metrics.memory_mb:.1f}MB > {thresholds['memory_mb']}MB",
                "value": metrics.memory_mb,
                "threshold": thresholds["memory_mb"]
            })
            
        # Alerte CPU
        if metrics.cpu_percent > thresholds["cpu_percent"]:
            alerts.append({
                "type": "cpu",
                "level": "warning", 
                "message": f"High CPU usage: {metrics.cpu_percent:.1f}% > {thresholds['cpu_percent']}%",
                "value": metrics.cpu_percent,
                "threshold": thresholds["cpu_percent"]
            })
            
        # Alerte temps de réponse
        if metrics.response_time > thresholds["response_time"]:
            alerts.append({
                "type": "response_time",
                "level": "critical",
                "message": f"Slow response: {metrics.response_time:.1f}s > {thresholds['response_time']}s",
                "value": metrics.response_time,
                "threshold": thresholds["response_time"]
            })
            
        # Alerte status
        if metrics.status not in ["healthy", "warning"]:
            alerts.append({
                "type": "status",
                "level": "critical",
                "message": f"Service unhealthy: {metrics.status}",
                "value": metrics.status,
                "threshold": "healthy"
            })
            
        # Alerte taux d'erreur
        if metrics.success_rate < (1 - thresholds["error_rate"]) and metrics.success_rate > 0:
            error_rate = 1 - metrics.success_rate
            alerts.append({
                "type": "error_rate",
                "level": "warning",
                "message": f"High error rate: {error_rate:.2%} > {thresholds['error_rate']:.2%}",
                "value": error_rate,
                "threshold": thresholds["error_rate"]
            })
        
        return alerts
    
    def create_status_table(self, metrics: HealthMetrics, alerts: List[Dict]) -> Table:
        """Crée une table de status pour l'affichage"""
        table = Table(title=f"🕷️ EvaRAG Crawler Status - {datetime.now().strftime('%H:%M:%S')}")
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value", style="white", width=30)
        table.add_column("Status", width=15)
        
        # Status général
        status_color = {
            "healthy": "green",
            "warning": "yellow", 
            "degraded": "orange1",
            "down": "red"
        }.get(metrics.status, "red")
        
        table.add_row("Service Status", metrics.status.upper(), f"[{status_color}]●[/{status_color}]")
        table.add_row("Version", metrics.version, "✅" if metrics.version != "unknown" else "❓")
        table.add_row("v3.2 Features", "ENABLED" if metrics.v2_enabled else "DISABLED", 
                     "🆕" if metrics.v2_enabled else "🔒")
        
        table.add_section()
        
        # Métriques système
        memory_status = "🟢" if metrics.memory_mb < 800 else "🟡" if metrics.memory_mb < 1000 else "🔴"
        table.add_row("Memory", f"{metrics.memory_mb:.1f} MB", memory_status)
        
        cpu_status = "🟢" if metrics.cpu_percent < 60 else "🟡" if metrics.cpu_percent < 80 else "🔴"  
        table.add_row("CPU", f"{metrics.cpu_percent:.1f}%", cpu_status)
        
        response_status = "🟢" if metrics.response_time < 5 else "🟡" if metrics.response_time < 30 else "🔴"
        table.add_row("Response Time", f"{metrics.response_time:.2f}s", response_status)
        
        table.add_section()
        
        # Métriques métier
        uptime_human = str(timedelta(seconds=int(metrics.uptime_seconds)))
        table.add_row("Uptime", uptime_human, "⏱️")
        table.add_row("Active Jobs", str(metrics.active_jobs), "📋")
        
        if metrics.pages_crawled > 0:
            table.add_row("Pages Crawled", str(metrics.pages_crawled), "📄")
            table.add_row("Success Rate", f"{metrics.success_rate:.1%}", 
                         "✅" if metrics.success_rate > 0.9 else "⚠️" if metrics.success_rate > 0.7 else "❌")
        
        # Alertes
        if alerts:
            table.add_section()
            for alert in alerts:
                alert_icon = "🚨" if alert["level"] == "critical" else "⚠️"
                table.add_row("Alert", alert["message"][:40] + "...", alert_icon)
        
        return table
        
    def create_performance_chart(self) -> Panel:
        """Crée un graphique de performance simple en ASCII"""
        if len(self.metrics_history) < 2:
            return Panel("📈 Waiting for data...", title="Performance Trend")
            
        # Dernières 20 mesures
        recent_metrics = self.metrics_history[-20:]
        
        # Graphique ASCII simple pour la mémoire
        memory_values = [m.memory_mb for m in recent_metrics]
        min_mem, max_mem = min(memory_values), max(memory_values)
        
        chart_lines = []
        chart_lines.append(f"Memory Usage (MB): {min_mem:.0f} - {max_mem:.0f}")
        
        # Normalisation pour affichage
        if max_mem > min_mem:
            normalized = [(val - min_mem) / (max_mem - min_mem) for val in memory_values[-10:]]
            chart_line = ""
            for val in normalized:
                height = int(val * 8)
                chart_line += "▁▂▃▄▅▆▇█"[height] if height < 8 else "█"
            chart_lines.append(f"Memory: {chart_line}")
        
        # CPU
        cpu_values = [m.cpu_percent for m in recent_metrics[-10:]]
        chart_line = ""
        for val in cpu_values:
            height = min(int(val / 100 * 8), 7)
            chart_line += "▁▂▃▄▅▆▇█"[height]
        chart_lines.append(f"CPU:    {chart_line}")
        
        return Panel("\n".join(chart_lines), title="📊 Performance Chart")
    
    def save_metrics_snapshot(self, metrics: HealthMetrics, crawl_metrics: Optional[CrawlMetrics] = None):
        """Sauvegarde un snapshot des métriques"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = Path(self.config.export_dir) / f"metrics_{timestamp}.json"
        
        data = {
            "timestamp": timestamp,
            "health": asdict(metrics),
            "crawl": asdict(crawl_metrics) if crawl_metrics else None,
            "alerts": self.alerts_triggered[-10:],  # Dernières 10 alertes
            "config": asdict(self.config)
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
            
    async def run_test_crawl(self) -> Dict:
        """Lance un crawl de test pour vérifier les performances"""
        test_payload = {
            "urls": ["https://httpbin.org/html"],
            "depth": 1,
            "max_pages": 3,
            "strategy": "auto"
        }
        
        try:
            start_time = time.time()
            resp = await self.client.post(
                f"{self.config.base_url}/crawl",
                json=test_payload,
                timeout=120
            )
            duration = time.time() - start_time
            
            if resp.status_code == 200:
                result = resp.json()
                return {
                    "success": True,
                    "duration": duration,
                    "pages_crawled": result.get("summary", {}).get("total_pages", 0),
                    "version": result.get("summary", {}).get("version", "unknown")
                }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}",
                    "duration": duration
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "duration": 0
            }

# ==============================================
# MODES DE MONITORING
# ==============================================

async def live_monitoring_mode(config: MonitorConfig):
    """Mode monitoring temps réel avec interface live"""
    
    async with EvaRAGMonitor(config) as monitor:
        
        def signal_handler(signum, frame):
            monitor.stop_monitoring()
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=5)
        )
        
        layout["body"].split_row(
            Layout(name="main", ratio=2),
            Layout(name="chart", ratio=1)
        )
        
        with Live(layout, refresh_per_second=1, screen=True) as live:
            while monitor.running:
                try:
                    # Fetch metrics
                    health_metrics = await monitor.fetch_health_metrics()
                    if not health_metrics:
                        layout["header"].update(Panel("❌ Service unreachable", style="red"))
                        await asyncio.sleep(config.refresh_interval)
                        continue
                    
                    crawl_metrics = await monitor.fetch_crawl_metrics()
                    
                    # Store history
                    monitor.metrics_history.append(health_metrics)
                    if len(monitor.metrics_history) > config.max_history:
                        monitor.metrics_history.pop(0)
                        
                    if crawl_metrics:
                        monitor.crawl_history.append(crawl_metrics)
                        if len(monitor.crawl_history) > config.max_history:
                            monitor.crawl_history.pop(0)
                    
                    # Check alerts
                    alerts = monitor.check_alerts(health_metrics)
                    for alert in alerts:
                        alert["timestamp"] = time.time()
                        monitor.alerts_triggered.append(alert)
                    
                    # Update layout
                    header_text = f"🕷️ EvaRAG Monitor v3.2 | Service: {health_metrics.status.upper()} | v3.2: {'ON' if health_metrics.v2_enabled else 'OFF'}"
                    layout["header"].update(Panel(Align.center(header_text), style="blue"))
                    
                    # Main status
                    status_table = monitor.create_status_table(health_metrics, alerts)
                    layout["main"].update(Panel(status_table, title="📊 Status Dashboard"))
                    
                    # Performance chart
                    chart_panel = monitor.create_performance_chart()
                    layout["chart"].update(chart_panel)
                    
                    # Footer with alerts
                    if alerts:
                        alert_text = " | ".join([f"{a['level'].upper()}: {a['message'][:40]}" for a in alerts[-3:]])
                        layout["footer"].update(Panel(alert_text, title="🚨 Active Alerts", style="red"))
                    else:
                        stats_text = f"📈 History: {len(monitor.metrics_history)} samples | 🔄 Refresh: {config.refresh_interval}s"
                        layout["footer"].update(Panel(stats_text, title="📊 Monitoring Info", style="green"))
                    
                    await asyncio.sleep(config.refresh_interval)
                    
                except Exception as e:
                    monitor.console.print(f"❌ Monitoring error: {e}")
                    await asyncio.sleep(config.refresh_interval)

async def comparison_mode(config: MonitorConfig):
    """Mode comparaison avant/après déploiement"""
    
    console = Console()
    console.print("🔍 [bold blue]Performance Comparison Mode[/bold blue]")
    console.print("This will run tests to compare v3.1 vs v3.2 performance\n")
    
    async with EvaRAGMonitor(config) as monitor:
        
        # Test initial
        console.print("1️⃣ Running initial performance test...")
        test_result = await monitor.run_test_crawl()
        
        baseline_metrics = await monitor.fetch_health_metrics()
        if not baseline_metrics:
            console.print("❌ Cannot reach service for comparison")
            return
            
        console.print(f"✅ Baseline test completed:")
        console.print(f"   Duration: {test_result.get('duration', 0):.2f}s")
        console.print(f"   Pages: {test_result.get('pages_crawled', 0)}")
        console.print(f"   Version: {test_result.get('version', 'unknown')}")
        console.print(f"   v3.2 Features: {'ENABLED' if baseline_metrics.v2_enabled else 'DISABLED'}")
        
        # Recommandations
        console.print("\n📊 [bold]Performance Analysis:[/bold]")
        
        if baseline_metrics.v2_enabled:
            console.print("🆕 v3.2 improvements are ACTIVE")
            console.print("   Expected: Faster crawling, more pages, better error handling")
            
            if test_result.get('pages_crawled', 0) > 1:
                console.print("   ✅ BFS improvements working - multiple pages crawled")
            else:
                console.print("   ⚠️  Only 1 page crawled - check BFS configuration")
                
            if test_result.get('duration', 999) < 60:
                console.print("   ✅ Response time good - adaptive timeouts working") 
            else:
                console.print("   ⚠️  Slow response - check timeout configuration")
        else:
            console.print("🔒 Running in v3.1 compatibility mode")
            console.print("   To enable v3.2: Set ENABLE_CRAWLER_V2=true")
            
        # Memory analysis
        if baseline_metrics.memory_mb > 500:
            console.print(f"   📊 Memory usage: {baseline_metrics.memory_mb:.1f}MB - Monitor for leaks")
        else:
            console.print(f"   ✅ Memory usage: {baseline_metrics.memory_mb:.1f}MB - Good")
            
        # Save comparison data
        comparison_data = {
            "timestamp": datetime.now().isoformat(),
            "test_result": test_result,
            "baseline_metrics": asdict(baseline_metrics),
            "analysis": {
                "v2_enabled": baseline_metrics.v2_enabled,
                "performance_rating": "good" if test_result.get('duration', 999) < 60 else "needs_attention",
                "bfs_working": test_result.get('pages_crawled', 0) > 1,
                "memory_ok": baseline_metrics.memory_mb < 800
            }
        }
        
        comparison_file = Path(config.export_dir) / f"comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(comparison_file, 'w') as f:
            json.dump(comparison_data, f, indent=2)
            
        console.print(f"\n💾 Comparison data saved to: {comparison_file}")

async def alerts_mode(config: MonitorConfig):
    """Mode alertes - surveillance continue avec notifications"""
    
    console = Console()
    console.print("🚨 [bold red]Alert Monitoring Mode[/bold red]")
    console.print("Continuous monitoring with alerts\n")
    
    async with EvaRAGMonitor(config) as monitor:
        
        alert_count = 0
        last_alert_time = 0
        
        while monitor.running:
            try:
                metrics = await monitor.fetch_health_metrics()
                if not metrics:
                    console.print("❌ Service unreachable!")
                    await asyncio.sleep(config.refresh_interval)
                    continue
                
                alerts = monitor.check_alerts(metrics)
                
                # Nouvelle alerte
                for alert in alerts:
                    current_time = time.time()
                    # Éviter spam d'alertes (max 1 par minute du même type)
                    if current_time - last_alert_time > 60:
                        alert_count += 1
                        console.print(f"🚨 [bold red]ALERT #{alert_count}[/bold red] {alert['message']}")
                        
                        # Son d'alerte (si terminal le supporte)
                        if alert['level'] == 'critical':
                            print('\a')  # Bell character
                            
                        last_alert_time = current_time
                        
                        # Sauvegarde alert
                        alert_data = {
                            "id": alert_count,
                            "timestamp": datetime.now().isoformat(),
                            "alert": alert,
                            "metrics": asdict(metrics)
                        }
                        
                        alert_file = Path(config.export_dir) / f"alert_{alert_count:04d}.json"
                        with open(alert_file, 'w') as f:
                            json.dump(alert_data, f, indent=2)
                
                # Status régulier (si pas d'alerte)
                if not alerts and time.time() - last_alert_time > 300:  # Toutes les 5min si tout va bien
                    console.print(f"✅ {datetime.now().strftime('%H:%M:%S')} - Service healthy | "
                                f"Memory: {metrics.memory_mb:.0f}MB | "
                                f"CPU: {metrics.cpu_percent:.0f}% | "
                                f"v3.2: {'ON' if metrics.v2_enabled else 'OFF'}")
                    last_alert_time = time.time()
                
                await asyncio.sleep(config.refresh_interval)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"❌ Monitoring error: {e}")
                await asyncio.sleep(config.refresh_interval)
        
        console.print(f"\n📊 Alert session completed. {alert_count} alerts triggered.")

# ==============================================
# MAIN CLI
# ==============================================

async def main():
    parser = argparse.ArgumentParser(description="EvaRAG v3.2 Advanced Monitor")
    parser.add_argument("--base-url", default="http://localhost:11235", help="Service base URL")
    parser.add_argument("--interval", type=float, default=5.0, help="Refresh interval (seconds)")
    parser.add_argument("--export-dir", default="monitoring_data", help="Export directory")
    
    # Modes
    parser.add_argument("--live", action="store_true", help="Live monitoring dashboard")
    parser.add_argument("--compare", action="store_true", help="Performance comparison mode")  
    parser.add_argument("--alerts", action="store_true", help="Alert monitoring mode")
    parser.add_argument("--export", help="Export current metrics to file")
    
    # Configuration
    parser.add_argument("--memory-threshold", type=float, default=1000.0, help="Memory alert threshold (MB)")
    parser.add_argument("--cpu-threshold", type=float, default=80.0, help="CPU alert threshold (%)")
    parser.add_argument("--response-threshold", type=float, default=120.0, help="Response time threshold (s)")
    
    args = parser.parse_args()
    
    # Configuration
    config = MonitorConfig(
        base_url=args.base_url,
        refresh_interval=args.interval,
        export_dir=args.export_dir,
        alert_thresholds={
            "memory_mb": args.memory_threshold,
            "cpu_percent": args.cpu_threshold,
            "response_time": args.response_threshold,
            "error_rate": 0.1,
            "pages_per_minute": 5.0
        }
    )
    
    # Sélection du mode
    if args.live:
        await live_monitoring_mode(config)
    elif args.compare:
        await comparison_mode(config)
    elif args.alerts:
        await alerts_mode(config)
    elif args.export:
        async with EvaRAGMonitor(config) as monitor:
            metrics = await monitor.fetch_health_metrics()
            crawl_metrics = await monitor.fetch_crawl_metrics()
            
            if metrics:
                monitor.save_metrics_snapshot(metrics, crawl_metrics)
                print(f"✅ Metrics exported to {config.export_dir}")
            else:
                print("❌ Failed to fetch metrics")
    else:
        # Mode standard - monitoring simple
        console = Console()
        console.print("🕷️ [bold blue]EvaRAG v3.2 Monitor[/bold blue] - Standard Mode\n")
        
        async with EvaRAGMonitor(config) as monitor:
            for i in range(12):  # 1 minute de monitoring
                metrics = await monitor.fetch_health_metrics()
                if metrics:
                    status_emoji = {"healthy": "✅", "warning": "⚠️", "degraded": "🟠", "down": "❌"}.get(metrics.status, "❓")
                    console.print(f"{status_emoji} {datetime.now().strftime('%H:%M:%S')} | "
                                f"Status: {metrics.status} | "
                                f"Memory: {metrics.memory_mb:.0f}MB | "
                                f"CPU: {metrics.cpu_percent:.0f}% | "
                                f"Response: {metrics.response_time:.2f}s | "
                                f"v3.2: {'ON' if metrics.v2_enabled else 'OFF'}")
                else:
                    console.print("❌ Service unreachable")
                
                await asyncio.sleep(config.refresh_interval)
        
        console.print("\n📊 Standard monitoring completed")
        console.print("💡 Use --live for interactive dashboard")
        console.print("💡 Use --compare for performance analysis") 
        console.print("💡 Use --alerts for continuous monitoring")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Monitoring stopped by user")
