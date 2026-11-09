/* SPDX-License-Identifier: GPL-2.0-only */
struct __attribute__((packed)) record {
	unsigned char tag;
	unsigned long value;
};

unsigned long packed_load(const struct record *p)
{
	return p->value;
}

void packed_store(struct record *p, unsigned long value)
{
	p->value = value;
}

void byte_stores(unsigned char *p)
{
	p[1] = 1;
	p[2] = 2;
	p[3] = 3;
	p[4] = 4;
}
