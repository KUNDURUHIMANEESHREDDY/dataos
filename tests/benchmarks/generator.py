"""
Benchmark Data Generator for DataOS.
Produces synthetic datasets with known ground truth for entity/relationship discovery.
"""

import os
import csv
import json
import random
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Any, Tuple


@dataclass
class GroundTruthEntity:
    id: str
    canonical_name: str
    entity_type: str
    aliases: List[str] = field(default_factory=list)
    files_contained_in: List[str] = field(default_factory=list)


@dataclass
class GroundTruthRelationship:
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    evidence_file: str
    confidence: float = 1.0


@dataclass
class BenchmarkDataset:
    """Complete benchmark dataset with files and ground truth."""
    name: str
    files: Dict[str, str]  # filename -> file path
    entities: List[GroundTruthEntity]
    relationships: List[GroundTruthRelationship]
    schema_matches: Dict[str, List[str]]  # column_name -> [files it appears in]
    temp_dir: str = ""

    def entity_ids_by_type(self, etype: str) -> List[str]:
        return [e.id for e in self.entities if e.entity_type == etype]

    def relationships_as_tuples(self) -> List[Tuple[str, str, str]]:
        return [(r.source_entity_id, r.target_entity_id, r.relation_type) for r in self.relationships]


def generate_customer_order_dataset(temp_dir: str) -> BenchmarkDataset:
    """
    Generates a realistic multi-file dataset with known entity/relationship ground truth.

    Files:
      customers.csv   - 50 customers with IDs, names, emails, regions
      orders.csv      - 200 orders referencing customer_ids
      products.csv    - 30 products with IDs, names, categories, prices
      order_items.csv - 400 line items linking orders to products
      support_tickets.csv - 80 tickets from customers about products
      employees.csv   - 20 employees including sales reps linked to regions

    Ground truth entities: customers, products, employees, regions
    Ground truth relationships: customer->order, order->product, ticket->customer, etc.
    """
    os.makedirs(temp_dir, exist_ok=True)

    regions = ["North", "South", "East", "West", "Central"]
    categories = ["Electronics", "Clothing", "Food", "Books", "Sports"]

    # --- Ground truth entities ---
    customers = []
    for i in range(1, 51):
        name = f"Customer_{i}"
        email = f"customer{i}@example.com"
        region = regions[i % len(regions)]
        customers.append({
            "customer_id": f"C{i:04d}",
            "name": name,
            "email": email,
            "phone": f"555-{1000+i}",
            "region": region,
            "signup_date": f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
        })

    products = []
    for i in range(1, 31):
        products.append({
            "product_id": f"P{i:04d}",
            "product_name": f"Product_{categories[i % len(categories)]}_{i}",
            "category": categories[i % len(categories)],
            "price": round(10 + (i * 3.7), 2),
            "stock": random.randint(10, 500),
        })

    employees = []
    for i in range(1, 21):
        employees.append({
            "employee_id": f"E{i:04d}",
            "name": f"Employee_{i}",
            "role": random.choice(["Sales Rep", "Support Agent", "Manager"]),
            "region": regions[i % len(regions)],
            "email": f"employee{i}@company.com",
        })

    orders = []
    order_items = []
    for i in range(1, 201):
        cust = customers[i % len(customers)]
        order_id = f"O{i:04d}"
        orders.append({
            "order_id": order_id,
            "customer_id": cust["customer_id"],
            "order_date": f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
            "total_amount": round(50 + (i * 2.3), 2),
            "status": random.choice(["completed", "pending", "shipped"]),
        })
        # 1-3 items per order
        for j in range(random.randint(1, 3)):
            prod = products[(i + j) % len(products)]
            order_items.append({
                "order_id": order_id,
                "product_id": prod["product_id"],
                "quantity": random.randint(1, 5),
                "unit_price": prod["price"],
            })

    tickets = []
    for i in range(1, 81):
        cust = customers[i % len(customers)]
        prod = products[i % len(products)]
        tickets.append({
            "ticket_id": f"T{i:04d}",
            "customer_id": cust["customer_id"],
            "product_id": prod["product_id"],
            "subject": f"Issue with {prod['product_name']}",
            "status": random.choice(["open", "resolved", "pending"]),
            "created_at": f"2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
        })

    # --- Write CSV files ---
    files = {}

    def _write_csv(filename, rows, fieldnames):
        path = os.path.join(temp_dir, filename)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        files[filename] = path

    _write_csv("customers.csv", customers, list(customers[0].keys()))
    _write_csv("orders.csv", orders, list(orders[0].keys()))
    _write_csv("products.csv", products, list(products[0].keys()))
    _write_csv("order_items.csv", order_items, list(order_items[0].keys()))
    _write_csv("support_tickets.csv", tickets, list(tickets[0].keys()))
    _write_csv("employees.csv", employees, list(employees[0].keys()))

    # Also write a JSON file with employee-region mapping
    emp_region_path = os.path.join(temp_dir, "employee_regions.json")
    emp_regions = {e["employee_id"]: e["region"] for e in employees}
    with open(emp_region_path, "w") as f:
        json.dump(emp_regions, f, indent=2)
    files["employee_regions.json"] = emp_region_path

    # --- Ground truth entities ---
    gt_entities = []
    for c in customers:
        gt_entities.append(GroundTruthEntity(
            id=c["customer_id"], canonical_name=c["name"],
            entity_type="customer", aliases=[c["email"]],
            files_contained_in=["customers.csv"],
        ))
    for p in products:
        gt_entities.append(GroundTruthEntity(
            id=p["product_id"], canonical_name=p["product_name"],
            entity_type="product", aliases=[],
            files_contained_in=["products.csv"],
        ))
    for e in employees:
        gt_entities.append(GroundTruthEntity(
            id=e["employee_id"], canonical_name=e["name"],
            entity_type="employee", aliases=[e["email"]],
            files_contained_in=["employees.csv"],
        ))

    # --- Ground truth relationships ---
    gt_relationships = []
    seen_rels = set()
    for o in orders:
        key = (o["customer_id"], o["order_id"], "placed_order")
        if key not in seen_rels:
            gt_relationships.append(GroundTruthRelationship(
                source_entity_id=o["customer_id"], target_entity_id=o["order_id"],
                relation_type="placed_order", evidence_file="orders.csv",
            ))
            seen_rels.add(key)

    for oi in order_items:
        key = (oi["order_id"], oi["product_id"], "contains_product")
        if key not in seen_rels:
            gt_relationships.append(GroundTruthRelationship(
                source_entity_id=oi["order_id"], target_entity_id=oi["product_id"],
                relation_type="contains_product", evidence_file="order_items.csv",
            ))
            seen_rels.add(key)

    for t in tickets:
        key = (t["customer_id"], t["ticket_id"], "submitted_ticket")
        if key not in seen_rels:
            gt_relationships.append(GroundTruthRelationship(
                source_entity_id=t["customer_id"], target_entity_id=t["ticket_id"],
                relation_type="submitted_ticket", evidence_file="support_tickets.csv",
            ))
            seen_rels.add(key)
        key2 = (t["ticket_id"], t["product_id"], "about_product")
        if key2 not in seen_rels:
            gt_relationships.append(GroundTruthRelationship(
                source_entity_id=t["ticket_id"], target_entity_id=t["product_id"],
                relation_type="about_product", evidence_file="support_tickets.csv",
            ))
            seen_rels.add(key2)

    # --- Schema matches (columns appearing in multiple files) ---
    schema_matches = {
        "customer_id": ["customers.csv", "orders.csv", "support_tickets.csv"],
        "product_id": ["products.csv", "order_items.csv", "support_tickets.csv"],
        "order_id": ["orders.csv", "order_items.csv"],
        "region": ["customers.csv", "employees.csv"],
        "email": ["customers.csv", "employees.csv"],
    }

    return BenchmarkDataset(
        name="customer_order_ecommerce",
        files=files,
        entities=gt_entities,
        relationships=gt_relationships,
        schema_matches=schema_matches,
        temp_dir=temp_dir,
    )


def generate_text_corpus(temp_dir: str) -> BenchmarkDataset:
    """
    Generates a text corpus for knowledge extraction benchmarks.
    Articles mention entities (people, orgs, locations) and relationships between them.
    """
    os.makedirs(temp_dir, exist_ok=True)

    people = ["Alice Johnson", "Bob Smith", "Carol Williams", "David Brown", "Eva Martinez"]
    orgs = ["Acme Corp", "TechStart Inc", "GlobalTech", "DataFlow Systems", "CloudNine Ltd"]
    locations = ["New York", "San Francisco", "London", "Tokyo", "Berlin"]

    articles = []
    gt_entities = []
    gt_relationships = []
    seen = set()

    for i in range(20):
        p = people[i % len(people)]
        o = orgs[i % len(orgs)]
        l = locations[i % len(locations)]

        text = (
            f"Article {i+1}: {p} from {o} visited {l} for a conference. "
            f"The meeting discussed partnerships between {o} and other firms. "
            f"{p} spoke about innovation in data systems. "
            f"Contact: {p.lower().replace(' ', '.')}@{o.lower().replace(' ', '')}.com"
        )
        path = os.path.join(temp_dir, f"article_{i+1:03d}.txt")
        with open(path, "w") as f:
            f.write(text)
        articles.append(f"article_{i+1:03d}.txt")

        for entity_name, etype in [(p, "person"), (o, "organization"), (l, "location")]:
            eid = entity_name.lower().replace(" ", "_")
            if eid not in seen:
                gt_entities.append(GroundTruthEntity(
                    id=eid, canonical_name=entity_name, entity_type=etype,
                    files_contained_in=[f"article_{i+1:03d}.txt"],
                ))
                seen.add(eid)

        src = p.lower().replace(" ", "_")
        tgt = o.lower().replace(" ", "_")
        rel_key = (src, tgt, "works_for")
        if rel_key not in seen:
            gt_relationships.append(GroundTruthRelationship(
                source_entity_id=src, target_entity_id=tgt,
                relation_type="works_for", evidence_file=f"article_{i+1:03d}.txt",
            ))
            seen.add(rel_key)

        tgt2 = l.lower().replace(" ", "_")
        rel_key2 = (src, tgt2, "visited")
        if rel_key2 not in seen:
            gt_relationships.append(GroundTruthRelationship(
                source_entity_id=src, target_entity_id=tgt2,
                relation_type="visited", evidence_file=f"article_{i+1:03d}.txt",
            ))
            seen.add(rel_key2)

    files = {name: os.path.join(temp_dir, name) for name in articles}

    return BenchmarkDataset(
        name="text_corpus_knowledge",
        files=files,
        entities=gt_entities,
        relationships=gt_relationships,
        schema_matches={},
        temp_dir=temp_dir,
    )
