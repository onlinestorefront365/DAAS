"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-26 09:58:08.990866
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('businesses',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('source_record_id', sa.String(length=64), nullable=False),
    sa.Column('registered_state', sa.String(length=2), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('name_normalized', sa.Text(), nullable=False),
    sa.Column('entity_type_raw', sa.Text(), nullable=True),
    sa.Column('entity_category', sa.String(length=32), nullable=False),
    sa.Column('is_professional', sa.Boolean(), nullable=False),
    sa.Column('is_foreign', sa.Boolean(), nullable=False),
    sa.Column('home_jurisdiction', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=64), nullable=True),
    sa.Column('formed_on', sa.Date(), nullable=False),
    sa.Column('street1', sa.Text(), nullable=True),
    sa.Column('street2', sa.Text(), nullable=True),
    sa.Column('city', sa.Text(), nullable=True),
    sa.Column('region', sa.String(length=2), nullable=True),
    sa.Column('postal_code', sa.String(length=10), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('county', sa.Text(), nullable=True),
    sa.Column('address_kind', sa.String(length=24), nullable=True),
    sa.Column('contact_name', sa.Text(), nullable=True),
    sa.Column('registered_agent_name', sa.Text(), nullable=True),
    sa.Column('uses_commercial_agent', sa.Boolean(), nullable=False),
    sa.Column('industry', sa.String(length=48), nullable=True),
    sa.Column('is_holding_vehicle', sa.Boolean(), nullable=False),
    sa.Column('lead_score', sa.SmallInteger(), nullable=False),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('suppressed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('seq'),
    sa.UniqueConstraint('source', 'source_record_id', name='uq_business_source_record')
    )
    op.create_index('ix_business_formed', 'businesses', ['formed_on', 'id'], unique=False)
    op.create_index('ix_business_industry', 'businesses', ['industry'], unique=False)
    op.create_index('ix_business_name_trgm', 'businesses', ['name_normalized'], unique=False, postgresql_using='gin', postgresql_ops={'name_normalized': 'gin_trgm_ops'})
    op.create_index('ix_business_postal', 'businesses', ['postal_code'], unique=False)
    op.create_index('ix_business_state_formed', 'businesses', ['registered_state', 'formed_on'], unique=False)
    op.create_table('customers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('company', sa.Text(), nullable=True),
    sa.Column('plan', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('stripe_customer_id', sa.String(length=64), nullable=True),
    sa.Column('stripe_subscription_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('stripe_customer_id')
    )
    op.create_table('ingest_runs',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('since', sa.Date(), nullable=True),
    sa.Column('fetched', sa.Integer(), nullable=False),
    sa.Column('inserted', sa.Integer(), nullable=False),
    sa.Column('updated', sa.Integer(), nullable=False),
    sa.Column('skipped', sa.Integer(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ingest_runs_source'), 'ingest_runs', ['source'], unique=False)
    op.create_table('source_state',
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('watermark', sa.Date(), nullable=True),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('source')
    )
    op.create_table('api_keys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('prefix', sa.String(length=32), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash')
    )
    op.create_index(op.f('ix_api_keys_customer_id'), 'api_keys', ['customer_id'], unique=False)
    op.create_table('feeds',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('webhook_url', sa.Text(), nullable=False),
    sa.Column('secret', sa.String(length=64), nullable=False),
    sa.Column('cursor_seq', sa.BigInteger(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('consecutive_failures', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feeds_customer_id'), 'feeds', ['customer_id'], unique=False)
    op.create_table('rate_limit_windows',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('customer_id', 'window_start')
    )
    op.create_table('usage_counters',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('requests', sa.BigInteger(), nullable=False),
    sa.Column('records', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('customer_id', 'period')
    )
    op.create_table('feed_deliveries',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('feed_id', sa.UUID(), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('record_count', sa.Integer(), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['feed_id'], ['feeds.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feed_deliveries_feed_id'), 'feed_deliveries', ['feed_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_feed_deliveries_feed_id'), table_name='feed_deliveries')
    op.drop_table('feed_deliveries')
    op.drop_table('usage_counters')
    op.drop_table('rate_limit_windows')
    op.drop_index(op.f('ix_feeds_customer_id'), table_name='feeds')
    op.drop_table('feeds')
    op.drop_index(op.f('ix_api_keys_customer_id'), table_name='api_keys')
    op.drop_table('api_keys')
    op.drop_table('source_state')
    op.drop_index(op.f('ix_ingest_runs_source'), table_name='ingest_runs')
    op.drop_table('ingest_runs')
    op.drop_table('customers')
    op.drop_index('ix_business_state_formed', table_name='businesses')
    op.drop_index('ix_business_postal', table_name='businesses')
    op.drop_index('ix_business_name_trgm', table_name='businesses', postgresql_using='gin', postgresql_ops={'name_normalized': 'gin_trgm_ops'})
    op.drop_index('ix_business_industry', table_name='businesses')
    op.drop_index('ix_business_formed', table_name='businesses')
    op.drop_table('businesses')
