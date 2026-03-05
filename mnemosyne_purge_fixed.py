#!/usr/bin/env python3
"""
Project Mnemosyne's Purge - Fixed Version
Autonomous Process Management System with Adaptive Learning
Core Function: Monitors system resources, scores process criticality, 
and makes purge decisions with Firebase-backed state management.
"""

import os
import sys
import time
import json
import signal
import logging
import datetime
import traceback
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Tuple, Any, Set
from enum import Enum
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Third-party imports (standard, well-documented)
import psutil
import numpy as np
from firebase_admin import firestore, credentials, initialize_app
from google.cloud.firestore_v1 import Client as FirestoreClient

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/mnemosyne_purge.log')
    ]
)
logger = logging.getLogger("MnemosynePurge")


class ProcessState(Enum):
    """Process lifecycle states"""
    ACTIVE = "active"
    PURGE_CANDIDATE = "purge_candidate"
    PURGED = "purged"
    PROTECTED = "protected"
    EXITED = "exited"


class ErrorCategory(Enum):
    """Error categorization for adaptive learning"""
    RESOURCE_OVERFLOW = "resource_overflow"
    SCORING_FAILURE = "scoring_failure"
    FIREBASE_ERROR = "firebase_error"
    PROCESS_TERMINATION = "process_termination"
    CONFIGURATION = "configuration"


@dataclass
class ProcessMetrics:
    """Comprehensive process metrics"""
    pid: int
    name: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_rss: int = 0  # in bytes
    num_threads: int = 0
    create_time: float = 0.0
    status: str = ""
    exe: str = ""
    cmdline: List[str] = field(default_factory=list)
    username: str = ""
    io_counters: Optional[Any] = None
    connections: List[Any] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        """Convert to Firebase-compatible dictionary"""
        data = asdict(self)
        data['last_updated'] = datetime.datetime.fromtimestamp(self.last_updated)
        # Handle non-serializable fields
        if self.io_counters:
            data['io_counters'] = {
                'read_count': getattr(self.io_counters, 'read_count', 0),
                'write_count': getattr(self.io_counters, 'write_count', 0),
                'read_bytes': getattr(self.io_counters, 'read_bytes', 0),
                'write_bytes': getattr(self.io_counters, 'write_bytes', 0),
            }
        data['connections'] = len(self.connections)
        return data


@dataclass 
class Thresholds:
    """Dynamic resource thresholds with adaptive learning"""
    CPU_CRITICAL: float = 80.0
    RAM_CRITICAL: float = 80.0
    DISK_CRITICAL: float = 90.0
    IO_CRITICAL: float = 85.0
    SCORE_CUTOFF: float = 0.3
    CHECK_INTERVAL: int = 30
    GRACE_PERIOD: int = 300
    MAX_PURGES_PER_CYCLE: int = 5
    
    def adjust_based_on_load(self, system_load: float) -> None:
        """Dynamically adjust thresholds based on system load"""
        if system_load > 1.5:  # High load
            self.CPU_CRITICAL = max(70.0, self.CPU_CRITICAL * 0.9)
            self.SCORE_CUTOFF = min(0.5, self.SCORE_CUTOFF * 1.2)
        elif system_load < 0.5:  # Low load
            self.CPU_CRITICAL = min(90.0, self.CPU_CRITICAL * 1.1)
            self.SCORE_CUTOFF = max(0.2, self.SCORE_CUTOFF * 0.8)


@dataclass
class ScoringWeights:
    """Adaptive weights for survival-criticality scoring"""
    CPU_USAGE: float = 0.25
    MEMORY_USAGE: float = 0.25
    USER_IMPORTANCE: float = 0.15
    REVENUE_POTENTIAL: float = 0.20
    STRATEGIC_VALUE: float = 0.15
    EMOTIONAL_WEIGHT: float = 0.10
    RECENCY_BIAS: float = 0.05