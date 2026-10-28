// SPDX-License-Identifier: GPL-2.0-only
#include <linux/errno.h>
#include <linux/types.h>
#include <string.h>
#include <u-boot/crc.h>
#define JSMN_STATIC
#define JSMN_STRICT
#define JSMN_PARENT_LINKS
#include <net/httpd-jsmn.h>
#include "formats.h"

static u32 read_be32(const unsigned char *p)
{
	return (u32)p[0] << 24 | (u32)p[1] << 16 | (u32)p[2] << 8 | p[3];
}

static bool token_is(const char *json, const jsmntok_t *t, const char *value)
{
	return t->type == JSMN_STRING && t->end - t->start == strlen(value) &&
	       !memcmp(json + t->start, value, strlen(value));
}

/* OpenWrt fwtool INFO trailer: CRC covers the tar, info header and JSON.
 * This detects corruption, not authenticity. FIT hashes are checked separately. */
int tyfza1_check_sysupgrade(const void *data, size_t size, bool *factory_v1,
			  void (*poll)(void))
{
	const unsigned char *p = data, *tail;
	const char *json;
	jsmn_parser parser;
	jsmntok_t tokens[128];
	size_t info_size, json_size, offset, chunk;
	u32 crc = 0;
	int n, i, storage = 0, devices = 0;
	bool supported = false;
	*factory_v1 = false;
	if (size < 24) return -EINVAL;
	tail = p + size - 16;
	info_size = read_be32(tail + 12);
	if (memcmp(tail, "FWx0", 4) || tail[8] != 1 || tail[9] || tail[10] || tail[11] ||
	    info_size < 26 || info_size > 30 * 1024 + 24 || info_size > size ||
	    memcmp(p + size - info_size, "\0\0\0\0\0\0\0\0", 8)) return -EINVAL;
	for (offset = 0; offset < size - 16; offset += chunk) {
		chunk = size - 16 - offset;
		if (chunk > 0x10000) chunk = 0x10000;
		crc = crc32(crc, p + offset, chunk);
		poll();
	}
	if (~crc != read_be32(tail + 4)) return -EINVAL;
	json = (const char *)p + size - info_size + 8;
	json_size = info_size - 24;
	if (memchr(json, 0, json_size)) return -EINVAL;
	jsmn_init(&parser);
	n = jsmn_parse(&parser, json, json_size, tokens, 128);
	if (n < 1 || tokens[0].type != JSMN_OBJECT) return -EINVAL;
	for (i = tokens[0].end; i < json_size; i++)
		if (json[i] != ' ' && json[i] != '\t' && json[i] != '\r' && json[i] != '\n') return -EINVAL;
	for (i = 1; i < n; i++) {
		if (tokens[i].parent != 0) continue;
		if (token_is(json, &tokens[i], "tyfza1_storage")) {
			if (++storage > 1 || i + 1 >= n) return -EINVAL;
			*factory_v1 = token_is(json, &tokens[i + 1], "factory-v1");
		}
		if (token_is(json, &tokens[i], "supported_devices")) {
			int j;
			if (++devices > 1 || i + 1 >= n || tokens[i + 1].type != JSMN_ARRAY) return -EINVAL;
			for (j = i + 2; j < n && tokens[j].start < tokens[i + 1].end; j++)
				if (tokens[j].parent == i + 1 &&
				    token_is(json, &tokens[j], "tianyi,tyfza1")) supported = true;
		}
	}
	return supported ? 0 : -EINVAL;
}
