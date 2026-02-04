#!/usr/bin/env python3
"""
SDR Leads‑Tracking SQLite database helper.

A tiny library that creates (if necessary) an SQLite database with a schema
suitable for a Sales Development Representative (SDR) to track and qualify
leads.

Features:
- Leads can be assigned to multiple managers/representatives.
- Each lead stores a target (name, contacts, observations).
- Leads belong to a project (name, description).
- Simple status tracking.
- Helper CRUD functions to be used from other scripts or an interactive shell.
"""

from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Iterable, List, Tuple, Optional, Dict, Any

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DB_FILENAME = "sdr_leads.db"                     # SQLite file placed in the current directory
DB_PATH = Path.cwd() / DB_FILENAME


# ----------------------------------------------------------------------
# Database schema
# ----------------------------------------------------------------------
SCHEMA = """
-- Managers / Representatives (people who can be assigned leads)
CREATE TABLE IF NOT EXISTS manager (
    manager_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT UNIQUE
);

-- Projects to which leads belong
CREATE TABLE IF NOT EXISTS project (
    project_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    description  TEXT
);

-- Lead status lookup table
CREATE TABLE IF NOT EXISTS status (
    status_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE
);

-- Main lead record (now includes budget column)
CREATE TABLE IF NOT EXISTS lead (
    lead_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    target_name    TEXT NOT NULL,
    contacts       TEXT,                -- free‑form contacts (phone, email, etc.)
    observations   TEXT,
    budget         REAL,                -- optional monetary budget for the lead
    project_id     INTEGER NOT NULL REFERENCES project(project_id) ON DELETE CASCADE,
    status_id      INTEGER NOT NULL REFERENCES status(status_id) ON DELETE RESTRICT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Many‑to‑many relationship: a lead may be assigned to several managers
CREATE TABLE IF NOT EXISTS lead_manager (
    lead_id    INTEGER NOT NULL REFERENCES lead(lead_id) ON DELETE CASCADE,
    manager_id INTEGER NOT NULL REFERENCES manager(manager_id) ON DELETE CASCADE,
    PRIMARY KEY (lead_id, manager_id)
);
"""

# ----------------------------------------------------------------------
# Helper class
# ----------------------------------------------------------------------
class SDRDatabase:
    """Thin wrapper around SQLite for the SDR leads‑tracking tool."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self._seed_statuses()

    # --------------------------------------------------------------
    # Schema handling
    # --------------------------------------------------------------
    def _ensure_schema(self) -> None:
        """Create tables if they do not exist."""
        with self.conn:
            self.conn.executescript(SCHEMA)

    def _seed_statuses(self) -> None:
        """Insert default status values (idempotent)."""
        default_statuses = ["New", "Contacted", "Qualified", "Disqualified", "Won"]
        with self.conn:
            for name in default_statuses:
                self.conn.execute(
                    "INSERT OR IGNORE INTO status (name) VALUES (?)", (name,)
                )

    # --------------------------------------------------------------
    # CRUD – Managers
    # --------------------------------------------------------------
    def add_manager(self, name: str, email: Optional[str] = None) -> int:
        """Add a manager/representative and return its new manager_id."""
        cur = self.conn.execute(
            "INSERT INTO manager (name, email) VALUES (?, ?)", (name, email)
        )
        return cur.lastrowid

    def get_manager(self, manager_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM manager WHERE manager_id = ?", (manager_id,)
        )
        return cur.fetchone()

    def list_managers(self) -> List[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM manager ORDER BY name")
        return cur.fetchall()

    # --------------------------------------------------------------
    # CRUD – Projects
    # --------------------------------------------------------------
    def add_project(self, name: str, description: Optional[str] = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO project (name, description) VALUES (?, ?)",
            (name, description),
        )
        return cur.lastrowid

    def get_project(self, project_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM project WHERE project_id = ?", (project_id,)
        )
        return cur.fetchone()

    def list_projects(self) -> List[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM project ORDER BY name")
        return cur.fetchall()

    # --------------------------------------------------------------
    # CRUD – Leads
    # --------------------------------------------------------------
    def _status_id(self, status_name: str) -> int:
        """Resolve (or insert) a status name to its id."""
        cur = self.conn.execute(
            "SELECT status_id FROM status WHERE name = ?", (status_name,)
        )
        row = cur.fetchone()
        if row:
            return row["status_id"]
        cur = self.conn.execute(
            "INSERT INTO status (name) VALUES (?)", (status_name,)
        )
        return cur.lastrowid

    def add_lead(
        self,
        target_name: str,
        contacts: str,
        observations: str,
        project_id: int,
        status: str = "New",
        manager_ids: Optional[Iterable[int]] = None,
        budget: Optional[float] = None,
    ) -> int:
        """
        Insert a new lead and optionally assign it to managers.
        Returns the new lead_id.
        """
        status_id = self._status_id(status)
        cur = self.conn.execute(
            """
            INSERT INTO lead (target_name, contacts, observations, budget, project_id, status_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (target_name, contacts, observations, budget, project_id, status_id),
        )
        lead_id = cur.lastrowid
        if manager_ids:
            self.assign_managers(lead_id, manager_ids)
        return lead_id

    def assign_managers(self, lead_id: int, manager_ids: Iterable[int]) -> None:
        """Create (or replace) assignments of a lead to a set of managers."""
        with self.conn:
            for m_id in set(manager_ids):
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO lead_manager (lead_id, manager_id)
                    VALUES (?, ?)
                    """,
                    (lead_id, m_id),
                )

    def get_lead(self, lead_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a lead together with related info (project, status, managers)."""
        cur = self.conn.execute(
            """
            SELECT l.*, p.name AS project_name, s.name AS status_name
            FROM lead l
            JOIN project p ON l.project_id = p.project_id
            JOIN status s ON l.status_id = s.status_id
            WHERE l.lead_id = ?
            """,
            (lead_id,),
        )
        lead = cur.fetchone()
        if not lead:
            return None
        mgr_cur = self.conn.execute(
            """
            SELECT m.manager_id, m.name, m.email
            FROM manager m
            JOIN lead_manager lm ON m.manager_id = lm.manager_id
            WHERE lm.lead_id = ?
            """,
            (lead_id,),
        )
        managers = [dict(row) for row in mgr_cur.fetchall()]
        result = dict(lead)
        result["managers"] = managers
        return result

    def list_leads(self, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return a list of leads, optionally filtered by status name, with assigned managers included.
        Each lead dict will contain a "managers" key holding a list of manager dicts.
        """
        sql = """
            SELECT l.lead_id, l.target_name, l.contacts, l.observations, l.budget,
                   p.name AS project_name, s.name AS status_name,
                   l.created_at, l.updated_at
            FROM lead l
            JOIN project p ON l.project_id = p.project_id
            JOIN status s ON l.status_id = s.status_id
        """
        params: Tuple = ()
        if status:
            sql += " WHERE s.name = ?"
            params = (status,)
        sql += " ORDER BY l.created_at DESC"
        cur = self.conn.execute(sql, params)
        leads = [dict(row) for row in cur.fetchall()]
        # Attach managers to each lead
        for lead in leads:
            mgr_cur = self.conn.execute(
                """
                SELECT m.manager_id, m.name, m.email
                FROM manager m
                JOIN lead_manager lm ON m.manager_id = lm.manager_id
                WHERE lm.lead_id = ?
                """,
                (lead["lead_id"],),
            )
            lead["managers"] = [dict(m) for m in mgr_cur.fetchall()]
        return leads

    def update_lead_status(self, lead_id: int, new_status: str) -> None:
        """Change the status of a lead."""
        status_id = self._status_id(new_status)
        with self.conn:
            self.conn.execute(
                "UPDATE lead SET status_id = ?, updated_at = CURRENT_TIMESTAMP WHERE lead_id = ?",
                (status_id, lead_id),
            )

    def delete_lead(self, lead_id: int) -> None:
        """Remove a lead (cascades to lead_manager)."""
        with self.conn:
            self.conn.execute("DELETE FROM lead WHERE lead_id = ?", (lead_id,))

    # --------------------------------------------------------------
    # Utility
    # --------------------------------------------------------------
    def close(self) -> None:
        self.conn.close()


# ----------------------------------------------------------------------
# Example usage
# ----------------------------------------------------------------------
if __name__ == "__main__":
    db = SDRDatabase()
    # 1️⃣ Add managers (multiple)
    alice_id = db.add_manager("Alice Johnson", "alice@example.com")
    bob_id   = db.add_manager("Bob Smith", "bob@example.com")
    carol_id = db.add_manager("Carol Lee", "carol@example.com")
    dave_id  = db.add_manager("Dave Patel", "dave@example.com")
    
    # 2️⃣ Create several projects
    proj_a_id = db.add_project(
        name="Enterprise CRM Rollout",
        description="Implement a new CRM system for enterprise sales."
    )
    proj_b_id = db.add_project(
        name="SMB Outreach Campaign",
        description="Target small‑business customers with a new product line."
    )
    proj_c_id = db.add_project(
        name="International Expansion",
        description="Explore leads in the APAC region."
    )
    
    # 3️⃣ Insert a variety of leads covering different use‑cases
    # Lead 1 – New lead, budget, multiple managers
    lead1_id = db.add_lead(
        target_name="Acme Corp",
        contacts="john.doe@acme.com, +1‑555‑123‑4567",
        observations="Interested in API integration; budget $50k.",
        project_id=proj_a_id,
        status="New",
        manager_ids=[alice_id, bob_id],
        budget=50000.0,
    )
    
    # Lead 2 – Contacted, no budget, single manager
    lead2_id = db.add_lead(
        target_name="Beta LLC",
        contacts="susan@beta.com, +1‑555‑987‑6543",
        observations="Demo scheduled for next week.",
        project_id=proj_b_id,
        status="Contacted",
        manager_ids=[carol_id],
    )
    
    # Lead 3 – Qualified, larger budget, multiple managers
    lead3_id = db.add_lead(
        target_name="Gamma Industries",
        contacts="info@gamma.io",
        observations="Potential $200k deal.",
        project_id=proj_c_id,
        status="Qualified",
        manager_ids=[alice_id, dave_id],
        budget=200000.0,
    )
    
    # Lead 4 – Disqualified, no manager assignment
    lead4_id = db.add_lead(
        target_name="Delta Startup",
        contacts="founder@delta.io",
        observations="No budget, decided to look elsewhere.",
        project_id=proj_b_id,
        status="Disqualified",
        manager_ids=None,
    )
    
    # Lead 5 – Won, single manager, budget
    lead5_id = db.add_lead(
        target_name="Epsilon Enterprises",
        contacts="contact@epsilon.com",
        observations="Closed deal, implementation in Q3.",
        project_id=proj_a_id,
        status="Won",
        manager_ids=[bob_id],
        budget=75000.0,
    )
    
    # 4️⃣ Retrieve and pretty‑print one lead as a sanity check
    lead = db.get_lead(lead1_id)
    from pprint import pprint
    print("Sample lead (lead1):")
    pprint(lead)
    
    # 5️⃣ List all leads (shows attached managers)
    print("\nAll leads:")
    pprint(db.list_leads())
    
    # 6️⃣ Filter leads by a specific status
    print("\nQualified leads:")
    pprint(db.list_leads(status="Qualified"))
    
    db.close()
    
    
