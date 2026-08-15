CREATE TABLE order_catalog_references (
    order_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    service_type_id TEXT NOT NULL,
    pallet_size_id TEXT NOT NULL,
    PRIMARY KEY (order_id, organization_id),
    FOREIGN KEY (order_id, organization_id)
        REFERENCES orders(id, organization_id),
    FOREIGN KEY (service_type_id, organization_id)
        REFERENCES service_types(id, organization_id),
    FOREIGN KEY (pallet_size_id, organization_id)
        REFERENCES pallet_sizes(id, organization_id)
);

CREATE INDEX idx_order_catalog_references_service_type
    ON order_catalog_references (organization_id, service_type_id);
CREATE INDEX idx_order_catalog_references_pallet_size
    ON order_catalog_references (organization_id, pallet_size_id);
