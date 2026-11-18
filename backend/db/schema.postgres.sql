-- KarigarSetu tables (postgres). Generated from app/models.py by: python -m app.schema_dump
-- The app creates these automatically; this file is for reference or manual setup.

CREATE TYPE accountstatus AS ENUM ('pending', 'approved', 'rejected');

CREATE TYPE orderstatus AS ENUM ('awaiting_maker', 'counter_offered', 'approved', 'in_production', 'ready', 'delivered', 'rejected');

CREATE TABLE admin_session (
	token VARCHAR NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (token)
);

CREATE TABLE auditlog (
	id SERIAL NOT NULL, 
	ts TIMESTAMP WITH TIME ZONE NOT NULL, 
	maker_id INTEGER, 
	order_code VARCHAR, 
	actor VARCHAR NOT NULL, 
	action VARCHAR NOT NULL, 
	detail VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_auditlog_maker_id ON auditlog (maker_id);
CREATE INDEX ix_auditlog_order_code ON auditlog (order_code);
CREATE INDEX ix_auditlog_ts ON auditlog (ts);

CREATE TABLE contact_message (
	id SERIAL NOT NULL, 
	name VARCHAR NOT NULL, 
	email VARCHAR NOT NULL, 
	phone VARCHAR NOT NULL, 
	message VARCHAR NOT NULL, 
	emailed BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE conversation (
	phone VARCHAR NOT NULL, 
	maker_id INTEGER, 
	history VARCHAR NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (phone)
);

CREATE TABLE maker (
	id SERIAL NOT NULL, 
	name VARCHAR NOT NULL, 
	phone VARCHAR NOT NULL, 
	place VARCHAR NOT NULL, 
	buffer_days INTEGER NOT NULL, 
	min_order INTEGER NOT NULL, 
	language VARCHAR NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_maker_phone ON maker (phone);

CREATE TABLE message (
	id SERIAL NOT NULL, 
	ts TIMESTAMP WITH TIME ZONE NOT NULL, 
	direction VARCHAR NOT NULL, 
	phone VARCHAR NOT NULL, 
	body VARCHAR NOT NULL, 
	order_code VARCHAR, 
	delivered BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_message_phone ON message (phone);

CREATE TABLE retailer (
	id SERIAL NOT NULL, 
	name VARCHAR NOT NULL, 
	phone VARCHAR NOT NULL, 
	city VARCHAR NOT NULL, 
	language VARCHAR NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_retailer_phone ON retailer (phone);

CREATE TABLE makersession (
	token VARCHAR NOT NULL, 
	maker_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (token), 
	FOREIGN KEY(maker_id) REFERENCES maker (id)
);

CREATE TABLE product (
	id SERIAL NOT NULL, 
	maker_id INTEGER NOT NULL, 
	code VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	price_per_pair INTEGER NOT NULL, 
	pairs_per_day INTEGER NOT NULL, 
	sizes VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(maker_id) REFERENCES maker (id)
);
CREATE INDEX ix_product_maker_id ON product (maker_id);

CREATE TABLE supplier_account (
	id SERIAL NOT NULL, 
	maker_id INTEGER, 
	name VARCHAR NOT NULL, 
	business_name VARCHAR NOT NULL, 
	craft VARCHAR NOT NULL, 
	town VARCHAR NOT NULL, 
	phone VARCHAR NOT NULL, 
	email VARCHAR NOT NULL, 
	password_hash VARCHAR NOT NULL, 
	status accountstatus NOT NULL, 
	failed_logins INTEGER NOT NULL, 
	locked_until TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(maker_id) REFERENCES maker (id)
);
CREATE UNIQUE INDEX ix_supplier_account_email ON supplier_account (email);
CREATE INDEX ix_supplier_account_maker_id ON supplier_account (maker_id);
CREATE UNIQUE INDEX ix_supplier_account_phone ON supplier_account (phone);

CREATE TABLE "order" (
	id SERIAL NOT NULL, 
	code VARCHAR NOT NULL, 
	maker_id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	retailer_id INTEGER, 
	retailer_name VARCHAR NOT NULL, 
	retailer_phone VARCHAR NOT NULL, 
	city VARCHAR NOT NULL, 
	language VARCHAR NOT NULL, 
	price_per_pair INTEGER NOT NULL, 
	status orderstatus NOT NULL, 
	proposed_date DATE, 
	due_date DATE, 
	reserved_ready INTEGER NOT NULL, 
	to_make INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(maker_id) REFERENCES maker (id), 
	FOREIGN KEY(product_id) REFERENCES product (id), 
	FOREIGN KEY(retailer_id) REFERENCES retailer (id)
);
CREATE UNIQUE INDEX ix_order_code ON "order" (code);
CREATE INDEX ix_order_maker_id ON "order" (maker_id);
CREATE INDEX ix_order_retailer_id ON "order" (retailer_id);

CREATE TABLE stock (
	id SERIAL NOT NULL, 
	product_id INTEGER NOT NULL, 
	size INTEGER NOT NULL, 
	ready INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (product_id, size), 
	FOREIGN KEY(product_id) REFERENCES product (id)
);
CREATE INDEX ix_stock_product_id ON stock (product_id);

CREATE TABLE orderline (
	id SERIAL NOT NULL, 
	order_id INTEGER NOT NULL, 
	size INTEGER NOT NULL, 
	qty INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_id) REFERENCES "order" (id)
);
CREATE INDEX ix_orderline_order_id ON orderline (order_id);
