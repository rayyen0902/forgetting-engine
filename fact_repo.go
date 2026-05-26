package repository

import (
	"database/sql"
	"github.com/hufu/go-service/internal/model"
)

type FactRepo struct {
	db *sql.DB
}

func NewFactRepo(db *sql.DB) *FactRepo {
	return &FactRepo{db: db}
}

func (r *FactRepo) AddOrUpdate(tenantID, userID int64, content, category string) (*model.Fact, error) {
	f := &model.Fact{}
	err := r.db.QueryRow(
		`INSERT INTO facts (tenant_id, user_id, content, category)
		 VALUES ($1,$2,$3,$4)
		 ON CONFLICT (tenant_id, user_id, content)
		 DO UPDATE SET updated_at = NOW(), retrieval_count = facts.retrieval_count + 1
		 RETURNING fact_id, tenant_id, user_id, content, category, trust_score, retrieval_count, created_at, updated_at`,
		tenantID, userID, content, category,
	).Scan(&f.ID, &f.TenantID, &f.UserID, &f.Content, &f.Category, &f.TrustScore, &f.RetrievalCount, &f.CreatedAt, &f.UpdatedAt)
	return f, err
}

func (r *FactRepo) Search(tenantID, userID int64, query string, limit int) ([]model.Fact, error) {
	rows, err := r.db.Query(
		`SELECT fact_id, tenant_id, user_id, content, category, trust_score, retrieval_count, created_at, updated_at
		 FROM facts
		 WHERE tenant_id = $1 AND user_id = $2 AND content ILIKE '%' || $3 || '%'
		 ORDER BY trust_score DESC
		 LIMIT $4`,
		tenantID, userID, query, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var facts []model.Fact
	for rows.Next() {
		var f model.Fact
		if err := rows.Scan(&f.ID, &f.TenantID, &f.UserID, &f.Content, &f.Category, &f.TrustScore, &f.RetrievalCount, &f.CreatedAt, &f.UpdatedAt); err != nil {
			return nil, err
		}
		facts = append(facts, f)
	}
	return facts, nil
}
