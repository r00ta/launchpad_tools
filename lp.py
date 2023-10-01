import argparse
import sqlite3
from datetime import datetime
from launchpadlib.launchpad import Launchpad

CACHEDIR = "./cache"
BUG_STATES = ['New', "Fix Committed",]

class Storage():
    def __init__(self, name) -> None:
        self.con = self._create_database(name)
        self._create_tables()

    def _create_database(self, name="issues"):
        db_name = f"{name}.db"
        con = sqlite3.connect(db_name)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    def _create_tables(self):
        cur = self.con.cursor()
        cur.executescript("""
        -- Table to store text content and its embeddings
        CREATE TABLE IF NOT EXISTS texts (
            text_id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS embeddings (
            text_id INTEGER NOT NULL,
            embedding BLOB,
            FOREIGN KEY (text_id) REFERENCES texts(text_id)
        );

        -- Table to store issues
        CREATE TABLE IF NOT EXISTS issues (
            bug_id INTEGER PRIMARY KEY,
            date_created DATETIME NOT NULL,
            date_last_updated DATETIME NOT NULL,
            web_link TEXT NOT NULL,
            title_id INTEGER NOT NULL,
            description_id INTEGER NOT NULL,
            FOREIGN KEY (title_id) REFERENCES texts(text_id),
            FOREIGN KEY (description_id) REFERENCES texts(text_id)
        );

        -- Table to store issue comments
        CREATE TABLE IF NOT EXISTS issue_comments (
            bug_id INTEGER NOT NULL,
            text_id INTEGER NOT NULL,
            FOREIGN KEY (bug_id) REFERENCES issues(bug_id),
            FOREIGN KEY (text_id) REFERENCES texts(text_id)
        );
        """)
        cur.close()
    
    def print_bug(self, bug, verbose=False):
        print(f"LP#{b.bug.id}: [{b.status}] {b.bug.title}")
        if verbose:
            print(f"URL: {b.bug.web_link}")
            print(f"Created: {b.bug.date_created}")
            print(f"Last Updated: {b.bug.date_last_updated}")
            print(f"Description: {b.bug.description}")
            for i, m in enumerate(b.bug.messages):
                print(f"Comment #{i}")
                print(f"{m.content}\n")
            print("*"*20)

    def store_bug(self, b):
        cur = self.con.cursor()
        try:
            # Check if bug already exists and get its last updated date
            cur.execute("SELECT date_last_updated FROM issues WHERE bug_id = ?", (b.bug.id,))
            existing_bug = cur.fetchone()

            if existing_bug is None or datetime.strptime(existing_bug[0], "%Y-%m-%d %H:%M:%S.%f%z") < b.bug.date_last_updated:
                self.con.execute("BEGIN TRANSACTION")
                # Bug is not in database or is outdated, so insert or update it
                title_id = cur.execute("INSERT INTO texts (content) VALUES (?)", (b.bug.title,)).lastrowid
                description_id = cur.execute("INSERT INTO texts (content) VALUES (?)", (b.bug.description,)).lastrowid
                if existing_bug is None:
                    # Insert new bug
                    cur.execute("""
                        INSERT INTO issues (bug_id, date_created, date_last_updated, web_link, title_id, description_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (b.bug.id, b.bug.date_created, b.bug.date_last_updated, b.bug.web_link, title_id, description_id))
                else:
                    # Update existing bug
                    cur.execute("""
                        UPDATE issues SET date_last_updated = ?, title_id = ?, description_id = ?
                        WHERE bug_id = ?
                    """, (b.bug.date_last_updated, title_id, description_id, b.bug.id))

                # Delete existing comments before adding updated comments
                cur.execute("DELETE FROM issue_comments WHERE bug_id = ?", (b.bug.id,))
                cur.execute("DELETE FROM texts WHERE text_id IN (SELECT text_id FROM issue_comments WHERE bug_id = ?)", (b.bug.id,))
                cur.execute("DELETE FROM embeddings WHERE text_id IN (SELECT text_id FROM issue_comments WHERE bug_id = ?)", (b.bug.id,))

                # Insert comments data
                for i, m in enumerate(b.bug.messages):
                    comment_id = cur.execute("INSERT INTO texts (content) VALUES (?)", (m.content,)).lastrowid
                    cur.execute("INSERT INTO issue_comments (bug_id, text_id) VALUES (?, ?)", (b.bug.id, comment_id))

                self.con.commit()
                self.print_bug(b, verbose=True)
            else:
                print(f"Bug LP#{b.bug.id} [{b.status}] is up to date, skipping...")
        except Exception as e:
            self.con.rollback();
            print(f"When processing bug {b.bug.id}, an error occurred: {e}")
        finally:
            cur.close()

    def generate_embedding(self, content):
        # Placeholder method for now
        return content[:16]

    def update_embeddings(self):
        cur = self.con.cursor()
        try:
            # Get all text entries
            cur.execute("SELECT text_id, content FROM texts")
            all_texts = cur.fetchall()

            for text_id, content in all_texts:
                # Start a transaction for each embedding creation
                self.con.execute("BEGIN TRANSACTION")  

                # Check if embedding already exists
                cur.execute("SELECT 1 FROM embeddings WHERE text_id = ?", (text_id,))
                if cur.fetchone() is None:
                    # Generate and insert embedding
                    embedding = self.generate_embedding(content)
                    cur.execute("INSERT INTO embeddings (text_id, embedding) VALUES (?, ?)",
                                (text_id, embedding))

                self.con.commit()  # Commit the transaction after each embedding creation

        except Exception as e:
            self.con.rollback()  # Rollback the transaction in case of error
            print(f"An error occurred: {e}")
        finally:
            cur.close()

    def close(self):
        self.con.close()

if __name__=="__main__":
    parser = argparse.ArgumentParser(
        prog='launchpad-bug-triage',
        description='Launchpad Bug Triage Assistant',
    )
    parser.add_argument('-p', '--project', default='maas', help='Launchpad project name')
    args = parser.parse_args()

    st = Storage(args.project)
    lp = Launchpad.login_with("Bug Triage Assistant", "production", CACHEDIR, version="devel")
    project = lp.projects[args.project]
    bugs = project.searchTasks(status=BUG_STATES)
    for b in bugs:
        st.store_bug(b)
    st.update_embeddings()
    st.close()
