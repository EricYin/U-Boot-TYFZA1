/* SPDX-License-Identifier: GPL-2.0-only */
/* Exercise the pinned lwIP input/ACK path with a finite NI receive ring.
 * The CPU is paused during each sender burst; this is a loss reproduction,
 * not a timing model of the Cortex-A55 or a measured throughput benchmark. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lwip/init.h"
#include "lwip/tcp.h"
#include "lwip/priv/tcp_priv.h"
#include "lwip/ip4.h"
#include "lwip/inet_chksum.h"
#include "lwip/prot/tcp.h"
#include "lwip/prot/ip4.h"

static struct netif nic;
static u32_t received, announced, acknowledged;
u32_t sys_now(void) { return 0; }
static err_t output(struct netif *n, struct pbuf *p, const ip4_addr_t *dst)
{
	unsigned char buf[1600];
	(void)n; (void)dst;
	pbuf_copy_partial(p, buf, sizeof(buf), 0);
	struct tcp_hdr *tcp = (void *)(buf + IPH_HL_BYTES((struct ip_hdr *)buf));
	announced = (u32_t)lwip_ntohs(tcp->wnd) << TCP_RCV_SCALE;
	acknowledged = lwip_ntohl(tcp->ackno);
	return ERR_OK;
}
static err_t accepted(void *arg, struct tcp_pcb *pcb, struct pbuf *p, err_t error)
{
	(void)arg; (void)error;
	if (!p) return ERR_OK;
	received += p->tot_len;
	tcp_recved(pcb, p->tot_len);
	pbuf_free(p);
	return ERR_OK;
}
static void packet(u32_t seq, u16_t length)
{
	struct pbuf *p = pbuf_alloc(PBUF_RAW, 40 + length, PBUF_RAM);
	if (!p) abort();
	memset(p->payload, 0, p->tot_len);
	struct ip_hdr *ip = p->payload;
	struct tcp_hdr *tcp = (void *)((unsigned char *)p->payload + 20);
	IPH_VHL_SET(ip, 4, 5); IPH_LEN_SET(ip, lwip_htons(p->tot_len));
	IPH_TTL_SET(ip, 64); IPH_PROTO_SET(ip, IP_PROTO_TCP);
	ip4_addr_t src, dst;
	IP4_ADDR(&src, 192,168,0,2); IP4_ADDR(&dst, 192,168,0,1);
	ip4_addr_copy(ip->src, src); ip4_addr_copy(ip->dest, dst);
	tcp->src=lwip_htons(50000); tcp->dest=lwip_htons(80);
	tcp->seqno=lwip_htonl(seq); tcp->ackno=lwip_htonl(1);
	TCPH_HDRLEN_FLAGS_SET(tcp, 5, TCP_ACK);
	tcp->wnd=lwip_htons(65535);
	pbuf_remove_header(p,20);
	tcp->chksum=inet_chksum_pseudo(p,IP_PROTO_TCP,p->tot_len,&src,&dst);
	pbuf_add_header(p,20);
	IPH_CHKSUM_SET(ip, inet_chksum(ip,20));
	ip4_input(p,&nic);
}
int main(void)
{
	lwip_init();
	IP_ADDR4(&nic.ip_addr,192,168,0,1);
	IP_ADDR4(&nic.netmask,255,255,255,0);
	nic.mtu=1500;nic.flags=NETIF_FLAG_UP|NETIF_FLAG_LINK_UP;
	nic.output=output;nic.name[0]='n';nic.name[1]='i';
	netif_list=&nic;netif_default=&nic;
	struct tcp_pcb *pcb=tcp_new();
	if (!pcb) abort();
	IP_ADDR4(&pcb->local_ip,192,168,0,1);IP_ADDR4(&pcb->remote_ip,192,168,0,2);
	pcb->local_port=80;pcb->remote_port=50000;pcb->state=ESTABLISHED;
	pcb->mss=1460;pcb->rcv_nxt=1;pcb->rcv_wnd=TCP_WND;
	pcb->rcv_ann_wnd=TCP_WND;pcb->rcv_ann_right_edge=1+TCP_WND;
	pcb->snd_nxt=pcb->lastack=pcb->snd_lbb=1;pcb->snd_wnd=65535;
	pcb->flags|=TF_WND_SCALE;pcb->rcv_scale=TCP_RCV_SCALE;
	tcp_recv(pcb,accepted);tcp_active_pcbs=pcb;
	unsigned int dropped=0, frames=0, rounds=0;u32_t seq=1;
	announced=TCP_WND;acknowledged=1;
	for (rounds=0; rounds<100; rounds++) {
		unsigned int burst=announced/1460;
		if (burst>10)burst=10; /* Ordinary initial congestion window. */
		if (!burst)abort();
		unsigned int slot=(1518+16+7)&~7U;
		unsigned int capacity=(NI_TEST_RX_BYTES-8)/slot;
		unsigned int keep=burst<capacity?burst:capacity;
		dropped+=burst-keep;frames+=burst;
		for(unsigned int i=0;i<keep;i++)packet(seq+i*1460,1460);
		seq+=burst*1460;
		if(dropped)break;
		if(acknowledged!=seq){fprintf(stderr,"ACK did not advance: %u/%u\n",acknowledged,seq);return 1;}
	}
	printf("{\"window\":%u,\"frames\":%u,\"dropped\":%u,\"received\":%u,\"ack\":%u}\n",TCP_WND,frames,dropped,received,acknowledged);
	if (!received) return 1;
	return 0;
}
